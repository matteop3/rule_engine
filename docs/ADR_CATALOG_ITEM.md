# ADR: Catalog Item

## Status

**Accepted**

## Context

Part identities in the rule engine are shared between two subsystems: `BOMItem` (technical and commercial BOM lines on an EntityVersion) and `PriceListItem` (priced entries on a price list). A centralized catalog is the standard way master-data-driven ERPs and CPQ systems solve this. SAP exposes it as the `Material Master`, Oracle / NetSuite as the `Item Master`, Tacton and Configit assume a catalog synchronized from PLM. Arena and Windchill push it further with revisions and lifecycle states. In all of them the common principle holds: **a part number is an entity, not a string.**

Key design questions:

1. What metadata lives on the catalog vs. on BOM items and price list items?
2. How is the catalog referenced — by surrogate id or by business key?
3. What lifecycle states does the catalog support, and how do they interact with existing references?
4. How does catalog metadata reach the calculation response?
5. What deletion semantics preserve audit safety without making the table effectively append-only?
6. How does the catalog relate to future PLM-style features (revisions, reference BOMs, multi-level compositions)?

## Decisions

### 1. Flat `catalog_items` table, one row per part identity

A single SQL table `catalog_items` holds the authoritative description, unit of measure, category, lifecycle status, and free-form notes for each part. There is no hierarchy, no reference composition, and no revision table. The catalog answers one question only: "does this part exist, and what is its canonical metadata?"

The table uses `AuditMixin` (`created_at`, `updated_at`, `created_by_id`, `updated_by_id`) so master-data changes are attributable.

**Why flat.** A hierarchy-capable catalog conflates two concerns: identity ("what is this part?") and typical composition ("how is it usually built?"). Keeping those separate leaves room for a `CatalogTemplate` layer above the catalog without forcing the decision now.

### 2. Business-key foreign key on `part_number`

`BOMItem.part_number` and `PriceListItem.part_number` remain `VARCHAR(100)` columns and become foreign keys to `CatalogItem.part_number`. No new `catalog_item_id` surrogate column is added to either child table.

- The external API contract is preserved end-to-end: clients continue to send and receive `part_number` strings on `BOMItem`, `PriceListItem`, `BOMLineItem`, and `CalculationResponse`.
- The invariant "part_number is never renamed in place" (decision #4) makes the business key safe as an FK target.
- Joins are straightforward and the BOM aggregation key `(part_number, parent_bom_item_id, bom_type)` is unaffected.

### 3. Lifecycle: `ACTIVE` and `OBSOLETE` only

`status` accepts two values: `ACTIVE` (default) and `OBSOLETE`. No intermediate states (`IN_REVIEW`, `PENDING`, etc.) — the minimal lifecycle is enough to express the only operation that matters for the current scope: retiring a part without breaking historical references.

Effects of `OBSOLETE`:

- Existing `BOMItem` and `PriceListItem` rows that reference an `OBSOLETE` entry continue to work unchanged. The rule engine evaluates them, the price resolver prices them, the output lists them normally.
- Creating a new `BOMItem` or `PriceListItem` that references an `OBSOLETE` entry is blocked with HTTP 409.
- Updating an existing `BOMItem` or `PriceListItem` to point at an `OBSOLETE` entry is blocked with HTTP 409.
- Transition from `OBSOLETE` back to `ACTIVE` is permitted.

Error messages (exact copy, for API consistency):

- On create: `"Catalog item '<part_number>' is OBSOLETE and cannot be referenced by new items"`
- On update: `"Catalog item '<part_number>' is OBSOLETE and cannot be referenced"`

### 4. `part_number` is never renamed in place

`CatalogItem.part_number` is immutable after creation. `PATCH /catalog-items/{id}` rejects any payload containing `part_number` with HTTP 422 and the message `"part_number cannot be modified; obsolete the entry and create a new one instead"`.

The immutability exists for three reasons:

1. It is the business-key FK target. A silent rename would break referential integrity across `bom_items` and `price_list_items`.
2. It is the stability guarantee for future retroactive classification of custom items (see the `CustomItemPromotion` follow-up in `ADR_CUSTOM_ITEMS.md`): the promotion mapping relies on stable `part_number` values to resolve historical references.
3. It matches master-data practice in every major ERP: part numbers are identifiers; to rename a part, obsolete it and issue a new one.

### 5. Centralized metadata: `description`, `category`, `unit_of_measure`

Canonical metadata lives on the catalog and nowhere else:

- `description` is mandatory, stored as `TEXT`, and serves as the single source of truth for human-readable part naming.
- `unit_of_measure` is mandatory, `VARCHAR(20)`, with server default `'PC'` (pieces). Every part declares a unit.
- `category` is optional, `VARCHAR(100)`, used for grouping in UI listings.
- `notes` is optional free text. Deliberately **not** an enum — no premature taxonomy.

`BOMItem.description`, `BOMItem.category`, `BOMItem.unit_of_measure`, and `PriceListItem.description` are not stored on their respective rows. The engine joins to the catalog at calculation time to populate `BOMLineItem.description` / `category` / `unit_of_measure` in the response.

### 6. Deletion governed by referential integrity, not by FINALIZED state

`DELETE /catalog-items/{id}` succeeds (HTTP 204) only when no live `BOMItem` and no live `PriceListItem` references the entry. It is blocked with HTTP 409 and an explicit count otherwise.

- A live reference is a row in `bom_items` or `price_list_items` — regardless of whether it lives on a DRAFT EntityVersion, a PUBLISHED EntityVersion, or a price list of any status.
- In practice a catalog entry referenced by a BOM item on a PUBLISHED EntityVersion is de facto undeletable, because the DRAFT-only editing rule prevents removing the BOM item. This is the correct behavior.
- The FINALIZED snapshot is self-contained JSON with no FK to the catalog, so deleting a catalog entry after its references are cleared does not corrupt historical configurations. The snapshot continues to describe the part as it was at finalization time.

Error message: `"Catalog item '<part_number>' cannot be deleted: referenced by N BOM item(s) and M price list item(s)"`.

### 7. CRUD endpoint surface and RBAC

Path prefix: `/catalog-items`.

| Method | Path | Roles | Description |
|---|---|---|---|
| `GET` | `/catalog-items` | any authenticated | List. Query params: `status`, `skip`, `limit`. Ordered by `part_number` ASC. |
| `GET` | `/catalog-items/{id}` | any authenticated | Get by surrogate `id`. |
| `GET` | `/catalog-items/by-part-number/{part_number}` | any authenticated | Get by business key. |
| `POST` | `/catalog-items` | ADMIN, AUTHOR | Create. HTTP 409 on duplicate `part_number`. |
| `PATCH` | `/catalog-items/{id}` | ADMIN, AUTHOR | Update description, unit_of_measure, category, status, notes. HTTP 422 on `part_number` in payload. |
| `DELETE` | `/catalog-items/{id}` | ADMIN, AUTHOR | Delete if unreferenced. HTTP 409 otherwise. |

Reads are authenticated but unrestricted by role — same pattern used by `/price-lists` and `/price-list-items`.

### 8. Engine sources `BOMLineItem` metadata from the catalog at calculation time

`BOMLineItem` exposes `part_number`, `description`, `category`, `unit_of_measure`, `quantity`, `unit_price`, `line_total`. The schema shape is unchanged; only the source of the three metadata fields moved from BOM item columns to catalog columns.

Concretely:

- At the start of BOM evaluation, the engine loads all `CatalogItem` rows referenced by the current EntityVersion into an in-memory `dict[str, CatalogItem]` keyed by `part_number` (single `IN` query).
- Each `BOMLineItem` reads description, category, and unit of measure from this map.
- A missing entry (which the FK on `bom_items.part_number` should make impossible) raises a clear internal error naming the part; the message flags a corrupted EntityVersion rather than silently falling back.
- The catalog is **not** cached in the PUBLISHED EntityVersion in-memory cache. It is loaded per calculation, consistent with how price lists are loaded per calculation (see `ADR_PRICE_LIST.md` decision #10). Mutations to a catalog row are visible to the next call even when the cached `VersionData` is reused.

### 9. Snapshot immunity to catalog mutation

When a configuration is finalized, the `CalculationResponse` is serialized into `Configuration.snapshot` as self-contained JSON. The snapshot carries the catalog-sourced metadata at finalization time. Subsequent mutations to catalog rows — including `status = OBSOLETE` and full deletion (after clearing other references) — never alter the FINALIZED document. The immutability guarantee is the same one that protects against price list mutation (see `ADR_REHYDRATION.md`): the snapshot is the authoritative read path for FINALIZED configurations.

### 10. CRUD-level validation on BOMItem and PriceListItem references

Both `POST /bom-items` / `PATCH /bom-items/{id}` and `POST /price-list-items` / `PATCH /price-list-items/{id}` validate the `part_number`:

- Missing entry → HTTP 409 with `"Catalog item '<part_number>' does not exist"`.
- OBSOLETE entry → HTTP 409 with the exact messages from decision #3.
- ACTIVE entry → accepted.

The FK constraint at the database level catches integrity violations, but the application-layer validation is what produces the meaningful error responses and handles the OBSOLETE gating (which the FK alone cannot express).

### 11. Test fixtures auto-seed the catalog for BOM and price list rows

The test suite needed a refactor when the FK landed. Rather than rewriting every fixture that constructs a `BOMItem` or `PriceListItem`, a SQLAlchemy `before_flush` session event listener inspects pending rows and upserts matching `CatalogItem` entries with neutral defaults (description = part_number, unit = `'PC'`, status = `ACTIVE`). A module-level monkeypatch replaces `validate_catalog_reference` with a lenient no-op in the default test environment. Tests that need to exercise the real CRUD validation opt in via the `strict_catalog_validation` fixture, which restores the real validator.

This keeps the fixture call sites unchanged while making the new FK invariant invisible to tests that don't care about it.

## Consequences

- **Positive**: single source of truth for part identity and metadata. `description`, `category`, `unit_of_measure` have one authoritative home.
- **Positive**: typos no longer create silent phantom parts — unknown `part_number` values are rejected at CRUD time.
- **Positive**: lifecycle (`OBSOLETE`) is expressible without deletion, so historical references remain intact.
- **Positive**: external API shape is unchanged. Clients still send and receive `part_number` strings; the catalog is an internal integrity layer.
- **Positive**: future integration with a PLM or ERP has a home. A catalog sync job updates `catalog_items`; no schema change in BOM or price list code.
- **Negative**: creating a `BOMItem` or `PriceListItem` now requires a pre-existing catalog entry. AUTHOR workflows that used to fire-and-forget a part number now need a catalog-entry step first.
- **Negative**: the catalog is loaded per calculation (not cached). If load patterns demand it, a dedicated short-TTL cache can be added later, mirroring the path left open for price lists.

## Out of Scope

| Feature | Rationale |
|---|---|
| Revision tracking on catalog items | No `rev_A` / `rev_B`. Part identity today is the `part_number`. |
| `replaced_by` auto-rerouting | `OBSOLETE` gates new references; automatic forwarding of existing references is a workflow concern. |
| PLM / ERP synchronization | The catalog is locally managed. External sync can be added additively later. |
| Multi-currency on the catalog | Pricing stays on the price list and on custom items. Catalog entries carry no price. |
| Bulk import endpoints | Single-row CRUD is enough for the first release. Bulk import is a follow-up. |
| Optimistic locking (ETags) | Cross-cutting gap, noted in `ADR_PRICE_LIST.md`, not addressed here. |
| Engineering BOM / auto-explosion on catalog insert | See `CatalogTemplate` follow-up below. |

## Known Gaps and Follow-ups

### CatalogTemplate (reference BOM / auto-explosion)

**Scenario.** When an AUTHOR adds a composite catalog item — say `MOUSE-PRO` — to a technical BOM, it would be useful for its typical sub-components (cable, connector, housing) to appear automatically rather than being entered by hand.

**What it would be.** A separate pair of tables (`CatalogTemplate` + `CatalogTemplateItem`) that stores one or more "typical compositions" per catalog root, with its own internal parent-child hierarchy. At design time, an action "explode template" creates BOMItem rows in the current EntityVersion DRAFT. The resulting BOMItems are detached from the template: later updates to the template do not propagate to already-exploded BOMItems.

**Why this keeps the catalog flat.** The catalog answers "what exists". The template is a separate layer above the catalog that answers "how is it typically composed". This preserves the invariant that EntityVersion is the sole runtime source of truth for product structure — matching SAP's separation of Material Master and Reference BOM.

**Principle of the future solution.** The template is a **boilerplate generator** invoked on demand, not a live composition that the engine dereferences at calculation time. The current flat catalog remains load-bearing; adding templates later is additive. No migration of existing catalog rows is needed when this lands.

**Why postponed.** Dedicated chapter, not on the critical path of the current scope. The catalog is a prerequisite for the template, but not vice versa. Add it when concrete need emerges from AUTHOR workflows.

### Bulk import of catalog items

Real catalogs contain hundreds or thousands of parts. The current CRUD surface is one-row-at-a-time and does not expose a bulk endpoint. Single-row CRUD is enough for demos, tests, and the greenfield release; the first production migration will need a bulk loader.

## Related

- [ADR: BOM Generation](ADR_BOM.md) — BOM structure; the catalog supersedes the per-BOMItem metadata columns.
- [ADR: Price List](ADR_PRICE_LIST.md) — Pricing still lives on the price list; the catalog supersedes `PriceListItem.description`.
- [ADR: Re-hydration](ADR_REHYDRATION.md) — FINALIZED snapshot immunity to catalog mutation follows the same mechanism as price list immunity.
