# Part Catalog & Custom Items — Analysis and Plan

**Status:** Approved, ready for implementation
**Scope:** Two related features delivered in sequence
**Related ADRs:** [ADR_BOM.md](ADR_BOM.md), [ADR_PRICE_LIST.md](ADR_PRICE_LIST.md), [ADR_REHYDRATION.md](ADR_REHYDRATION.md)

---

## 1. Purpose of this document

This is the **reference specification** for two features that build on top of the existing BOM and Price List subsystems:

1. **CatalogItem** (Phase 1) — a centralized catalog of part identities, inspired by the SAP Material Master / Oracle Item Master pattern. Replaces the current practice of storing `part_number` as a free string duplicated across `BOMItem` and `PriceListItem`.
2. **ConfigurationCustomItem** (Phase 2) — an escape hatch for one-off commercial line items that do not exist in the catalog, added at configuration time by the end user.

This document is the single source of truth: every design decision, every invariant, every API contract, every goal, and every non-goal is recorded here. The accompanying [PART_CATALOG_DEVLOG.md](PART_CATALOG_DEVLOG.md) breaks the work into phases for execution; this document answers "why" and "what", the devlog answers "how" and "in what order".

The implementation must keep project documentation in lockstep: `README.md`, existing ADRs (`ADR_BOM.md`, `ADR_PRICE_LIST.md`), the new ADRs created by these features, and `docs/TESTING.md`. Tests must cover both features comprehensively — CRUD, engine wiring, lifecycle, edge cases, RBAC.

---

## 2. Motivation

### 2.1 The problem with free-string part numbers

Today a `part_number` is a plain VARCHAR on `BOMItem` and another plain VARCHAR on `PriceListItem`, coupled only by naming convention. This leads to several concrete pain points:

- **Metadata duplication.** `description`, `category`, and `unit_of_measure` are stored on `BOMItem`; `description` is also stored on `PriceListItem`. Nothing prevents the same `BOLT-M8` from being described as "Bolt M8 zinc-plated" in one place and "Screw M8" in another.
- **No identity.** There is no authoritative answer to "does the part `BOLT-M8` exist?". A typo creates a new "part" silently.
- **No lifecycle.** There is no way to mark a part as obsolete, track replacements, or prevent its use in new quotes while preserving historical references.
- **No integration path.** Any future sync with a PLM or ERP system (`Arena`, `Windchill`, `SAP`) would need to reinvent part identity.

### 2.2 What the big players do

The approach described here is the well-trodden CPQ/ERP pattern:

- **SAP** — `Material Master` is the central anagraphic table. BOMs (`STPO`/`STKO`) and price conditions (`KONP`) reference it; they do not duplicate metadata.
- **Oracle / NetSuite** — `Item Master` plays the same role; BOM and price book are contextual layers above it.
- **Tacton / Configit / PROS** — the configurator never invents a `part_number`, it references a catalog typically synchronized from PLM.
- **Arena / Windchill (PLM)** — push it further with revisions, lifecycle states (In Work / Released / Obsolete), and effectivity dates.

The common principle: **a part number is an entity, not a string**.

### 2.3 The custom items problem

Even with a catalog, real quoting workflows need to price things that are not yet coded. Three patterns exist in the industry:

- **SAP / Oracle** — `text item` or `non-stock` line on the sales document: free description, manual price, lives only on the quote, never enters MRP, cannot have sub-components.
- **Tacton / Configit** — strict: if it is not in the catalog, it does not exist. Custom items are added downstream in the CRM/CPQ (Salesforce CPQ, SAP CPQ) as custom quote line items.
- **PLM-driven (Arena / Windchill)** — a "request for new part" workflow with approval, creating a provisional code that is later promoted.

The first pattern is the pragmatic fit: **the catalog is mandatory for the core, but explicit one-off lines can live directly on the configuration**, clearly marked as such so they never contaminate master-data features.

---

## 3. Goals and non-goals

### 3.1 Goals

- **G1.** Introduce a mandatory, flat `CatalogItem` table as the single source of truth for part identities, referenced by `BOMItem` and `PriceListItem` via foreign keys on `part_number`.
- **G2.** Centralize canonical metadata (`description`, `category`, `unit_of_measure`) on the catalog; remove the duplicated columns from `BOMItem` and `PriceListItem`.
- **G3.** Support a lifecycle status (`ACTIVE`, `OBSOLETE`) that prevents new references to deprecated parts while preserving historical ones.
- **G4.** Introduce `ConfigurationCustomItem` as a configuration-time escape hatch for commercial-only, one-off line items with inline price and description.
- **G5.** Keep the FINALIZED snapshot mechanism fully intact. Custom items and catalog-sourced lines both serialize into the snapshot; post-finalization mutations of the catalog or the custom items never alter a signed document.
- **G6.** Preserve the existing API contract on calculation: clients still send and receive `part_number` strings; the catalog is an internal integrity layer, not a schema change visible on the engine boundary.
- **G7.** Update all project documentation (README, ADR_BOM, ADR_PRICE_LIST, new ADRs, TESTING) and the full test suite in lockstep.

### 3.2 Non-goals (explicit)

- **NG1.** Revision tracking on catalog items (no `rev_A`, `rev_B`).
- **NG2.** `replaced_by` automatic rerouting of references. The data column can be added later if needed, but the current scope is only `ACTIVE` / `OBSOLETE`.
- **NG3.** PLM / ERP synchronization. The catalog is locally managed.
- **NG4.** Engineering BOM / auto-explosion of sub-components when a composite part is added to a technical BOM. See the `CatalogTemplate` follow-up in §10.
- **NG5.** Retroactive reclassification of custom items into catalog codes for reporting. See the `CustomItemPromotion` follow-up in §10.
- **NG6.** Multi-currency on catalog items. Pricing stays on the price list and on custom items; catalog entries do not carry prices.
- **NG7.** Bulk import endpoints for catalog items. A single-row CRUD surface is enough for the first release.
- **NG8.** Optimistic locking via ETags. Already a known cross-cutting gap in [ADR_PRICE_LIST.md](ADR_PRICE_LIST.md); not addressed here.
- **NG9.** Conditional inclusion (`BOMItemRule`-style) on custom items. If the user adds a custom item, they want it.
- **NG10.** Technical BOM support for custom items. Custom items exist only in the commercial BOM.
- **NG11.** Discount or negative pricing on custom items. See §6.2 validation rules.
- **NG12.** Schema versioning of the snapshot. Already a known follow-up in [ADR_PRICE_LIST.md](ADR_PRICE_LIST.md).

---

## 4. CatalogItem — detailed design

### 4.1 Entity shape

A single SQL table `catalog_items`, with the following columns:

| Column | Type | Nullability | Default | Notes |
|---|---|---|---|---|
| `id` | `INTEGER PK` | NOT NULL | auto | Surrogate key for internal joins and for audit tables. |
| `part_number` | `VARCHAR(100)` | NOT NULL | — | Business key. `UNIQUE` constraint. Never renamed in place (see §4.4). |
| `description` | `TEXT` | NOT NULL | — | Canonical description. Single source of truth. Deduplicates what was previously on `BOMItem` and `PriceListItem`. |
| `unit_of_measure` | `VARCHAR(20)` | NOT NULL | `'PC'` | English abbreviation for "pieces". Mandatory to force every part to declare a unit. |
| `category` | `VARCHAR(100)` | NULLABLE | — | Grouping label (e.g. `"Chassis"`, `"Electronics"`). Moved from `BOMItem`. |
| `status` | `VARCHAR(20)` | NOT NULL | `'ACTIVE'` | Enum: `ACTIVE`, `OBSOLETE`. See §4.3. |
| `notes` | `TEXT` | NULLABLE | — | Free-text field for any contextual note (usage hints, supplier info, internal remarks). Deliberately **not** an enum — avoid premature taxonomy. |
| `created_at` | `DATETIME` | NOT NULL | `now()` | From `AuditMixin`. |
| `updated_at` | `DATETIME` | NOT NULL | `now()` | From `AuditMixin`. |
| `created_by_id` | `UUID FK` | NULLABLE | — | From `AuditMixin`. |
| `updated_by_id` | `UUID FK` | NULLABLE | — | From `AuditMixin`. |

Python enum:

```python
class CatalogItemStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    OBSOLETE = "OBSOLETE"
```

### 4.2 Foreign-key strategy (decision locked)

`BOMItem.part_number` and `PriceListItem.part_number` remain `VARCHAR(100)` columns and become foreign keys to `CatalogItem.part_number`. No new `catalog_item_id` surrogate column is added.

Rationale:

- The external API contract is preserved end-to-end: clients continue to send and receive `part_number` strings on `BOMItem`, `PriceListItem`, `BOMLineItem`, and the `CalculationResponse`.
- The invariant "part_number is never renamed in place" (§4.4) makes the business key safe as an FK target.
- No translation layer is needed at the API boundary.
- Joins are straightforward and the aggregation key on BOM evaluation (`(part_number, parent_bom_item_id, bom_type)`) is unaffected.

### 4.3 Lifecycle and `OBSOLETE` semantics (decision locked)

`status` accepts two values: `ACTIVE` (default) and `OBSOLETE`.

**Effects of transitioning a catalog item to `OBSOLETE`:**

- Existing `BOMItem` and `PriceListItem` rows that reference it **continue to work unchanged**. The rule engine calculates them, the price resolver prices them, the BOM output lists them normally. Obsoleting is not deletion.
- Creating a **new** `BOMItem` or `PriceListItem` that references an `OBSOLETE` entry is **blocked** with HTTP 409 Conflict.
- Updating an existing `BOMItem` or `PriceListItem` to change its `part_number` to an `OBSOLETE` entry is **blocked** with HTTP 409 Conflict.
- A transition from `OBSOLETE` back to `ACTIVE` is permitted (supports "oops, we needed it after all").

**Error messages** (exact copy required for API consistency):

- On create: `"Catalog item 'XYZ-001' is OBSOLETE and cannot be referenced by new items"`
- On update: `"Catalog item 'XYZ-001' is OBSOLETE and cannot be referenced"`

### 4.4 The never-renamed invariant

`CatalogItem.part_number` **must never be modified after creation**. Enforced at the CRUD layer: the `PATCH /catalog-items/{id}` endpoint rejects any payload containing `part_number` (HTTP 422, explicit error message `"part_number cannot be modified; obsolete the entry and create a new one instead"`).

This invariant exists for three reasons:

1. It is the business-key FK target (§4.2). A rename would silently break referential integrity across `BOMItem` and `PriceListItem`.
2. It is the stability guarantee for future retroactive classification (see the `CustomItemPromotion` follow-up in §10): the promotion mapping relies on stable `part_number` values to resolve historical references.
3. It matches master-data practice in all major ERP systems: part numbers are immutable identifiers; to "rename" a part you obsolete the old entry and create a new one.

### 4.5 Deletion (decision locked)

CatalogItem deletion is governed **purely by relational integrity** — there is no special check on FINALIZED configurations:

- `DELETE /catalog-items/{id}` succeeds (HTTP 204) if no live `BOMItem` and no live `PriceListItem` row references it.
- It is blocked with HTTP 409 if any reference exists, regardless of where that reference lives (DRAFT EntityVersion, PUBLISHED EntityVersion, active or expired PriceList).
- In practice this means a catalog item referenced by a `BOMItem` on a PUBLISHED EntityVersion is de facto undeletable, because the DRAFT-only editing rule prevents removing the BOMItem. This is the correct behavior.
- The snapshot inside a FINALIZED configuration is self-contained JSON with no FK; deleting a catalog item does not corrupt it. The snapshot continues to describe the part exactly as it was at finalization time.

Error message: `"Catalog item 'XYZ-001' cannot be deleted: referenced by N BOM item(s) and M price list item(s)"`.

### 4.6 CRUD endpoint surface

Path prefix: `/catalog-items`.

| Method | Path | Roles | Description |
|---|---|---|---|
| `GET` | `/catalog-items` | any authenticated | List catalog items. Query params: `status` (optional filter), `skip`, `limit`. Ordered by `part_number` ASC. |
| `GET` | `/catalog-items/{id}` | any authenticated | Get one catalog item by surrogate `id`. |
| `GET` | `/catalog-items/by-part-number/{part_number}` | any authenticated | Get one catalog item by business key. |
| `POST` | `/catalog-items` | ADMIN, AUTHOR | Create. Rejects duplicates on `part_number` with HTTP 409. |
| `PATCH` | `/catalog-items/{id}` | ADMIN, AUTHOR | Update description, unit_of_measure, category, status, notes. Rejects `part_number` in payload with HTTP 422. |
| `DELETE` | `/catalog-items/{id}` | ADMIN, AUTHOR | Delete. Rejects with HTTP 409 if referenced. See §4.5. |

**Reads (GET)** are authenticated but unrestricted by role, to match the pattern used by `/price-lists` and `/price-list-items`.

### 4.7 Impact on `BOMItem`

| Change | Type |
|---|---|
| `description` column | **Removed.** Canonical description lives on `CatalogItem.description`. |
| `category` column | **Removed.** Canonical category lives on `CatalogItem.category`. |
| `unit_of_measure` column | **Removed.** Canonical UoM lives on `CatalogItem.unit_of_measure`. |
| `part_number` column | **Kept**, but now a foreign key to `CatalogItem.part_number`. `NOT NULL` unchanged. |

CRUD validation updates:

- `POST /bom-items` and `PATCH /bom-items/{id}`: the `part_number` in the payload must exist in `CatalogItem` and must reference an `ACTIVE` entry. Otherwise HTTP 409 with a descriptive error.
- Response schema `BOMItemRead`: no longer contains `description`, `category`, `unit_of_measure`. These fields are available via the catalog lookup and are returned as part of `BOMLineItem` in the calculation response (§7).

### 4.8 Impact on `PriceListItem`

| Change | Type |
|---|---|
| `description` column | **Removed.** Canonical description lives on `CatalogItem.description`. |
| `part_number` column | **Kept**, foreign key to `CatalogItem.part_number`. `NOT NULL` unchanged. |
| `unit_price` column | **Kept**, unchanged. Pricing stays on the price list item. |
| `valid_from` / `valid_to` | **Kept**, unchanged. Temporal validity stays here. |

CRUD validation updates:

- `POST /price-list-items` and `PATCH /price-list-items/{id}`: same rules as BOMItem — the `part_number` must exist in `CatalogItem` and must reference an `ACTIVE` entry.
- The `PriceListItemRead` response no longer contains `description`. Clients that need the description must look it up via the catalog, or it comes back as part of `BOMLineItem` at calculation time.

### 4.9 Engine integration (calculation path)

The rule engine currently builds each `BOMLineItem` with `description`, `category`, `unit_of_measure` sourced from `BOMItem`. After this change, these fields are sourced from the `CatalogItem` joined on `part_number`.

Concretely:

- At the start of BOM evaluation, the engine loads all `CatalogItem` rows referenced by the current `EntityVersion` into an in-memory map keyed by `part_number`.
- For every `BOMItem` in the version, the corresponding catalog entry provides `description`, `category`, and `unit_of_measure` for the output.
- The `BOMLineItem` Pydantic schema is **unchanged in shape**: it still exposes `part_number`, `description`, `category`, `unit_of_measure`, `quantity`, `unit_price`, `line_total`. Only the source of the metadata changes.
- If a `BOMItem` references a catalog entry that has since been obsoleted, evaluation **proceeds normally**. OBSOLETE is a lifecycle flag that gates *new* references; it does not retroactively invalidate existing ones.
- The catalog is **not cached** in the PUBLISHED EntityVersion in-memory cache. It is loaded per calculation, consistent with how the price list is loaded per calculation (see [ADR_PRICE_LIST.md](ADR_PRICE_LIST.md) decision #10). If performance measurements later justify caching, a dedicated short-TTL cache can be introduced.

### 4.10 Seed data

`seed_data.py` must be updated to create catalog entries **before** any `BOMItem` or `PriceListItem` that references them. The demo dataset adds a new section that creates one `CatalogItem` per distinct part number used in the existing BOM and price list demo data, with realistic descriptions, categories, and units of measure. The existing BOM items and price list items then reference these catalog entries by `part_number` (no payload change).

---

## 5. Alembic migration for Phase 1

The migration is split into logical steps within a single Alembic revision. Because the project is greenfield (no production data), the migration does not need to handle conflict resolution or legacy variants.

**Upgrade steps (in order):**

1. `CREATE TABLE catalog_items` with all columns from §4.1.
2. Create `UNIQUE` index on `catalog_items.part_number`.
3. **Data migration** — populate `catalog_items` by extracting distinct `part_number` values from `bom_items` and `price_list_items`:
   - Union the two sources.
   - For each distinct part_number, pick `description` from `price_list_items` first (more curated in practice), falling back to `bom_items.description`.
   - Pick `category` from `bom_items.category` (only BOMItem has this column currently); `NULL` if not present.
   - Pick `unit_of_measure` from `bom_items.unit_of_measure`, falling back to `'PC'` if `NULL`.
   - Set `status = 'ACTIVE'`, `notes = NULL`.
4. Add foreign key constraints from `bom_items.part_number` and `price_list_items.part_number` to `catalog_items.part_number`.
5. Drop `bom_items.description`.
6. Drop `bom_items.category`.
7. Drop `bom_items.unit_of_measure`.
8. Drop `price_list_items.description`.

**Downgrade steps (reverse):**

1. Re-add dropped columns on `bom_items` and `price_list_items` as nullable.
2. Backfill them by joining on `catalog_items` (same part_number).
3. Drop the foreign key constraints.
4. Drop the `catalog_items` table.

The downgrade is best-effort and not expected to be exercised in production; it is provided for developer convenience during local iteration.

---

## 6. ConfigurationCustomItem — detailed design

### 6.1 Entity shape

A single SQL table `configuration_custom_items`, tied to `configurations` via FK. These are **per-configuration** rows; they do not belong to an EntityVersion.

| Column | Type | Nullability | Default | Notes |
|---|---|---|---|---|
| `id` | `INTEGER PK` | NOT NULL | auto | Surrogate key. |
| `configuration_id` | `UUID FK` | NOT NULL | — | References `configurations.id`. `ON DELETE CASCADE`. |
| `custom_key` | `VARCHAR(20)` | NOT NULL | — | Format: `CUSTOM-<uuid8>`. `UNIQUE`. Auto-generated on insert (see §6.3). Used in BOM output as the `part_number` slot so downstream clients can treat it uniformly. |
| `description` | `TEXT` | NOT NULL | — | Free text, required. |
| `quantity` | `NUMERIC(12,4)` | NOT NULL | — | `CHECK (quantity > 0)`. |
| `unit_price` | `NUMERIC(12,4)` | NOT NULL | — | `CHECK (unit_price >= 0)`. Zero is valid (gift / included line for visibility); negative is rejected. |
| `unit_of_measure` | `VARCHAR(20)` | NULLABLE | — | Optional — custom items often don't have a formal UoM. |
| `sequence` | `INTEGER` | NOT NULL | `0` | Ordering among custom items within a configuration. |
| `created_at` | `DATETIME` | NOT NULL | `now()` | From `AuditMixin`. |
| `updated_at` | `DATETIME` | NOT NULL | `now()` | From `AuditMixin`. |
| `created_by_id` | `UUID FK` | NULLABLE | — | From `AuditMixin`. Answers "who added this uncoded line worth €5000?". |
| `updated_by_id` | `UUID FK` | NULLABLE | — | From `AuditMixin`. |

### 6.2 Value constraints (decision locked)

- `unit_price`: `NOT NULL`, `>= 0`. Zero is allowed (a $0 commercial line for a free add-on that should appear on the quote). Negative values and `NULL` are rejected.
- `quantity`: `NOT NULL`, `> 0`. Strictly positive. Zero or negative quantities are rejected.
- `description`: `NOT NULL`, non-empty string (stripped).

These constraints are enforced **both** at the database level (via `CHECK` constraints) and at the Pydantic schema layer (via validators), so they cannot be bypassed by sneaking past one layer.

### 6.3 Key generation

When a new `ConfigurationCustomItem` row is created, the server generates `custom_key` automatically as:

```
CUSTOM-<first-8-chars-of-uuid4-hex>
```

Example: `CUSTOM-a3f91b07`.

The client **cannot provide** `custom_key`. If present in the request payload, the value is ignored (Pydantic `exclude` / `extra="ignore"`).

This key is stable forever — never reused, never renumbered. It will serve as the anchor for the future `CustomItemPromotion` mechanism (§10).

### 6.4 Commercial-only (decision locked)

Custom items exist **only** in the commercial BOM output. There is no technical-BOM equivalent:

- If a part is not coded in the catalog, production does not know what to build.
- Engineering BOM semantics (hierarchy, sub-assemblies, production quantities) do not apply to a one-off quote line.

The BOM engine treats custom items as flat, root-level commercial lines — no `parent_bom_item_id`, no children, no conditional inclusion rules.

### 6.5 CRUD endpoint surface

Path prefix: `/configurations/{id}/custom-items`. Endpoints are nested under the configuration because custom items have no identity outside a configuration.

| Method | Path | Roles | Description |
|---|---|---|---|
| `GET` | `/configurations/{id}/custom-items` | owner + ADMIN | List custom items for this configuration. |
| `POST` | `/configurations/{id}/custom-items` | owner + ADMIN | Create a custom item. Configuration must be DRAFT. Server generates `custom_key`. |
| `PATCH` | `/configurations/{id}/custom-items/{custom_item_id}` | owner + ADMIN | Update description, quantity, unit_price, unit_of_measure, sequence. `custom_key` is immutable. Configuration must be DRAFT. |
| `DELETE` | `/configurations/{id}/custom-items/{custom_item_id}` | owner + ADMIN | Delete. Configuration must be DRAFT. |

**Authorization model:** a regular USER can only manipulate custom items on configurations they own. ADMIN can act on any configuration. This matches the existing authorization pattern on `/configurations/{id}` endpoints.

**DRAFT gating:** all mutations require `Configuration.status == DRAFT`. FINALIZED configurations return HTTP 409 on any write.

### 6.6 Engine integration

The rule engine gains a new step at the end of the PRICING pass:

```
 9. BOM        → evaluate inclusion, resolve quantities
10. PRICING    → resolve catalog prices from price list, compute catalog totals, emit warnings
11. CUSTOM     → append custom items from the configuration, add to commercial total
```

Mechanics:

- The engine loads `ConfigurationCustomItem` rows for the current configuration (if any) at calculation time.
- For each custom item, it emits a `BOMLineItem` with:
  - `part_number = custom_key` (e.g. `"CUSTOM-a3f91b07"`)
  - `description = custom_item.description`
  - `category = None`
  - `unit_of_measure = custom_item.unit_of_measure` (may be null)
  - `quantity = custom_item.quantity`
  - `unit_price = custom_item.unit_price`
  - `line_total = quantity * unit_price`
  - A new field `is_custom: bool = True` (see §6.7 for the schema change)
- Custom lines are appended **after** all catalog-sourced commercial lines in `BOMOutput.commercial`, respecting `sequence` for ordering within the custom block.
- `commercial_total` becomes `sum(catalog line totals with valid price) + sum(custom line totals)`.
- Custom items **never** generate warnings in `BOMOutput.warnings`. They are always complete by construction.
- Custom items **never** affect `is_complete`. Completeness is determined exclusively by catalog-line pricing (the partial-total + warnings mechanism from [ADR_PRICE_LIST.md](ADR_PRICE_LIST.md) §4), by mandatory fields, and by validation errors. Adding or removing custom items cannot unblock or block finalization.

**Stateless `POST /engine/calculate`:** custom items are **not** accessible from the stateless endpoint. They are tied to a persistent `Configuration` row; there is no sensible way to include them without the full configuration context. The stateless endpoint remains catalog-only, matching its current "preview-only" nature.

### 6.7 Schema changes

**`BOMLineItem`** (already in `app/schemas/engine.py`):

- Add field `is_custom: bool = False`. Default `False` so catalog lines remain untouched. Custom lines set it to `True`.
- This is an **additive** change — existing clients that ignore unknown fields continue to work.

**New schemas:**

- `CustomItemCreate` (fields: `description`, `quantity`, `unit_price`, `unit_of_measure?`, `sequence?`)
- `CustomItemUpdate` (same as Create but all fields optional)
- `CustomItemRead` (all fields including `id`, `custom_key`, audit fields)

### 6.8 Clone semantics

When a configuration is cloned (DRAFT → new DRAFT, or FINALIZED → new DRAFT):

- All `ConfigurationCustomItem` rows are **copied** to the new configuration.
- Each copy gets a **fresh `custom_key`** (new `CUSTOM-<uuid8>`). The old custom items and the new ones must not share keys, because they may later have different promotions or histories.
- The user can then remove unwanted custom items from the clone. Preserving them and letting the user delete them is safer than dropping them silently.

### 6.9 Upgrade semantics

When a DRAFT configuration is upgraded to a newer EntityVersion, custom items are **preserved as-is**. Custom items are decoupled from the entity model; they carry their own description and price and do not reference any field or BOM item. Upgrading changes the underlying version, not the custom lines.

### 6.10 Finalization and snapshot

- At finalization time, custom items are serialized into the `Configuration.snapshot` JSON blob together with the rest of the calculation response. The snapshot is fully self-contained.
- After finalization, custom items on the row become **read-only** — mutations return HTTP 409, consistent with the global "FINALIZED is immutable" rule.
- If the underlying `configuration_custom_items` rows are somehow modified later (e.g. by a developer bypassing the API), the snapshot remains authoritative: reads of FINALIZED configurations return the snapshot, never the live rows.
- Custom items in FINALIZED snapshots are not editable via any endpoint — this is enforced by the global FINALIZED write guard, not by a dedicated custom-items check.

### 6.11 Seed data

`seed_data.py` adds one or two example custom items to one of the existing DRAFT demo configurations, so the demo dataset exercises the custom-line code path end-to-end.

---

## 7. Alembic migration for Phase 2

A single revision that:

1. `CREATE TABLE configuration_custom_items` with all columns from §6.1, including the `CHECK` constraints for `quantity > 0` and `unit_price >= 0`.
2. `UNIQUE` index on `configuration_custom_items.custom_key`.
3. Regular index on `configuration_custom_items.configuration_id` for list queries.

No data migration is needed — Phase 2 introduces a new table, nothing is rewritten.

Downgrade: drop the table.

---

## 8. Test strategy

Both features demand broad test coverage. The existing suite has ~977 tests; the target after Phase 2 is comfortably above 1050.

### 8.1 Phase 1 tests (CatalogItem)

**API tests (`tests/api/test_catalog_items.py`, new file):**

- Create catalog item — happy path, duplicate `part_number` → 409, missing required fields → 422.
- Read — list with pagination, filter by status, get by id, get by part_number, 404 on unknown.
- Update — success on allowed fields, rejection of `part_number` in payload → 422, update `status` ACTIVE ↔ OBSOLETE.
- Delete — success when no references, 409 when referenced by BOMItem, 409 when referenced by PriceListItem, 409 when referenced by both.
- RBAC — reads allowed for any authenticated user, writes require ADMIN or AUTHOR, USER writes → 403.

**API tests (updates to `tests/api/test_bom_items.py` and `tests/api/test_price_list_items.py`):**

- Create BOMItem / PriceListItem referencing a non-existent `part_number` → 409 with explicit error.
- Create BOMItem / PriceListItem referencing an `OBSOLETE` catalog item → 409.
- Update BOMItem / PriceListItem changing `part_number` to an `OBSOLETE` entry → 409.
- Verify the response no longer contains `description` / `category` / `unit_of_measure` on BOMItem, and `description` on PriceListItem.

**Engine tests (updates to existing BOM test files):**

- BOM calculation output includes correct `description`, `category`, `unit_of_measure` in each `BOMLineItem`, sourced from the catalog.
- Changing the catalog description of a referenced part changes the next calculation output accordingly (DRAFT rehydration picks it up).
- Obsoleting a catalog item **does not** break the calculation for configurations still referencing it.
- FINALIZED configurations that referenced a later-obsoleted catalog item return the snapshot unchanged (description frozen).
- FINALIZED configurations that referenced a later-deleted catalog item (after all references are cleared) return the snapshot unchanged.

**Mutation kill tests:**

- Add at least two mutation-killing tests targeting the new validation logic (OBSOLETE check, non-existent part_number check).

### 8.2 Phase 2 tests (ConfigurationCustomItem)

**API tests (`tests/api/test_configuration_custom_items.py`, new file):**

- Create custom item — happy path, auto-generated `custom_key` starts with `CUSTOM-` and is 15 chars total, duplicate creation produces distinct keys.
- Create — client-provided `custom_key` is ignored (server always generates its own).
- Validation — `quantity = 0` → 422, `quantity = -1` → 422, `unit_price = -0.01` → 422, `unit_price = 0` accepted, missing `description` → 422.
- Create on FINALIZED configuration → 409.
- Create by USER on another user's configuration → 403.
- Update — allowed fields on DRAFT, rejected on FINALIZED, `custom_key` not modifiable.
- Delete — on DRAFT succeeds, on FINALIZED 409.
- List — returns all custom items for the configuration, ordered by `sequence`.

**Engine tests (`tests/engine/test_custom_items.py`, new file):**

- Custom items appear in `BOMOutput.commercial` after all catalog-sourced lines, with `is_custom = True`.
- `commercial_total` includes custom line totals.
- Custom items do **not** generate warnings.
- Custom items do **not** affect `is_complete` (neither block it nor unblock it).
- Mix of catalog items with missing prices + custom items: warnings list covers only catalog items, total is partial + custom contributions.
- `unit_price = 0` custom item produces `line_total = 0` and is included in the output normally.

**Integration tests (`tests/integration/test_custom_items_lifecycle.py`, new file):**

- End-to-end: create DRAFT, add custom items, calculate, finalize. Verify snapshot contains custom items with the exact values at finalization time.
- Mutate the custom items after finalization via the DB: verify FINALIZED read returns the snapshot (unchanged), not the mutated rows.
- Clone a FINALIZED configuration with custom items: new DRAFT contains copies with **new** `custom_key` values; snapshot of the source remains unchanged.
- Upgrade a DRAFT to a new EntityVersion: custom items are preserved.

**Mutation kill tests:**

- At least two targeting the value constraints (`quantity > 0`, `unit_price >= 0`).

### 8.3 Expected transient failures

Some phases in the devlog will intentionally leave the full suite in a broken state. This is expected and documented phase-by-phase in [PART_CATALOG_DEVLOG.md](PART_CATALOG_DEVLOG.md). The agent must not panic, must not try to "fix" tests whose failure is expected in the current phase, and must not run the suite in parallel. The devlog is the authoritative reference for "which tests should be failing right now and why".

---

## 9. Documentation updates

Documentation must stay in lockstep with the code. Each phase of the devlog that changes user-visible behavior or architecture also updates the relevant documents.

**Files that must be updated during Phase 1:**

- **`README.md`**
  - Update the domain model ERD to include `CatalogItem` with FKs from `BOMItem` and `PriceListItem`.
  - Add a "Catalog Management" section alongside the existing "Price List Management" and "BOM Generation" sections.
  - Update the API Overview table to list `/catalog-items` endpoints.
  - Update the project structure listing if new files appear.
- **`docs/ADR_BOM.md`**
  - Add a new decision point (or mark an existing one as superseded) reflecting that `BOMItem.description`, `category`, and `unit_of_measure` no longer live on the BOM item row.
  - Reference the new ADR_CATALOG_ITEM.md at the bottom under "Related".
- **`docs/ADR_PRICE_LIST.md`**
  - Add a note that `PriceListItem.description` is superseded by the catalog.
  - Reference ADR_CATALOG_ITEM.md under "Related".
- **`docs/ADR_CATALOG_ITEM.md` (new)**
  - Full ADR documenting all Phase 1 decisions (see §4 of this document as the input). Status: Accepted. Include a Known Gaps and Follow-ups section mentioning the postponed `CatalogTemplate`.
- **`docs/TESTING.md`**
  - Document the new test files and their scope.
  - Mention the new `ensure_catalog_entry` fixture helper (see §11).

**Files that must be updated during Phase 2:**

- **`README.md`**
  - Update the ERD to include `ConfigurationCustomItem`.
  - Add a "Custom Items" subsection under "BOM Generation" or a dedicated section.
  - Update the API Overview with the new `/configurations/{id}/custom-items` endpoints.
- **`docs/ADR_PRICE_LIST.md`**
  - Add a note that `BOMOutput` commercial lines may now include `is_custom = True` rows sourced from the configuration, and that custom items are always complete by construction (do not affect `is_complete`).
- **`docs/ADR_CUSTOM_ITEMS.md` (new)**
  - Full ADR documenting all Phase 2 decisions (see §6 of this document as the input). Status: Accepted. Include a Known Gaps and Follow-ups section mentioning the postponed `CustomItemPromotion`.
- **`docs/TESTING.md`**
  - Document the new custom-items test files.

### 9.1 Documentation style

All documentation updates must follow the existing project style: no incremental-change language. Describe the system **as it is**, not "we added X" / "we changed Y". Example: write "The catalog item table stores canonical part metadata" not "We added a catalog item table to centralize metadata".

---

## 10. Follow-ups explicitly out of scope

These are known, valuable extensions that are **intentionally not implemented** in this feature work. They must be documented in the respective new ADRs under a "Known Gaps and Follow-ups" section.

### 10.1 CatalogTemplate (reference BOM / auto-explosion)

**Scenario.** When an AUTHOR adds a composite catalog item (e.g. `MOUSE-PRO`) to a technical BOM, they would like its typical sub-components to appear automatically rather than being entered by hand.

**What it is.** A separate entity (`CatalogTemplate` + `CatalogTemplateItem`) that stores one or more "typical compositions" per catalog root, with its own internal parent-child hierarchy. When invoked at design time, it acts as a **boilerplate generator**: the action "explode template" creates BOMItem rows in the current EntityVersion DRAFT, detached from the template. Updates to the template do not propagate to already-exploded BOMItems.

**Why this keeps the catalog flat.** The catalog still answers "what exists". The template is a separate layer above the catalog that answers "how is it typically composed". This preserves the invariant that EntityVersion is the sole runtime source of truth for product structure, and matches SAP Reference BOM behavior.

**Why postponed.** Dedicated chapter, not on the critical path. The catalog is a prerequisite but not vice versa. Add it when concrete need emerges.

**Where documented.** Known Gaps section of `ADR_CATALOG_ITEM.md`.

### 10.2 CustomItemPromotion (retroactive reclassification)

**Scenario.** A FINALIZED configuration contains a custom item; later the business decides to code that part in the catalog. For reporting purposes, the business wants the historical custom line to be attributable to the new catalog code.

**What it is.** A separate mapping table `CustomItemPromotion(custom_key, promoted_to_part_number, promoted_at, promoted_by, notes?)`. Reporting queries `LEFT JOIN` on this mapping; queries that read the FINALIZED snapshot continue to see the original document unchanged. It is classification only, never recalculation: historical prices are not corrected, totals are not altered, `is_complete` is not touched. Reversible by deleting the promotion row.

**Why the two invariants matter now.** For this future mechanism to work additively, two stability guarantees must already hold in the current design:

1. `custom_key` values are stable forever (no reuse, no renumber). Achieved by auto-generation from UUID and standard PK-with-audit behavior.
2. `CatalogItem.part_number` values are never renamed in place. Achieved by the immutability rule in §4.4.

Both invariants are core to the present design and documented explicitly — they are not load-bearing *for* this feature, but they keep the door open *for* the future promotion feature.

**Why postponed.** We do not yet know if this will be used in practice. Real design depends on questions that can only be answered with concrete requirements (1-to-1 or 1-to-N? revocable? fuzzy matching? internal reporting or external data warehouse?). Zero cost of delay: the feature can be added as a purely additive migration when the need emerges.

**Where documented.** Known Gaps section of `ADR_CUSTOM_ITEMS.md`.

---

## 11. Test fixtures refactor (cross-cutting)

This is not a feature per se but a cross-cutting refactor that the devlog schedules as a dedicated phase. It is called out here because every test fixture and conftest that currently creates a `BOMItem` or `PriceListItem` with a free-string `part_number` must be updated to ensure a matching `CatalogItem` exists.

**Approach:**

- Introduce a helper `ensure_catalog_entry(db, part_number, description=None, ...)` in `tests/fixtures/` (new module, e.g. `tests/fixtures/catalog.py`).
- The helper looks up the catalog entry by `part_number`; if absent, it creates one with sensible defaults (`description = part_number`, `unit_of_measure = "PC"`, `status = ACTIVE`).
- Every existing fixture that creates a BOMItem or PriceListItem calls `ensure_catalog_entry(...)` first, passing the same `part_number`.
- This is done once centrally in the fixture module rather than scattered across individual test files.

**Why a dedicated phase:** because the new FK constraint is introduced in the same migration that renames/drops columns, every test that ran green before will start failing until the fixtures are updated. The devlog isolates this refactor in a single phase immediately after the migration phase.

---

## 12. Ordering summary

Feature work is delivered in two sequential sub-features, strictly in order:

1. **Feature A — CatalogItem.** Must be fully complete (code, tests, docs, seed) before Feature B begins. Custom items depend on the catalog existing but not vice versa.
2. **Feature B — ConfigurationCustomItem.** Builds on top of A and extends the BOM output pipeline.

Within each feature, [PART_CATALOG_DEVLOG.md](PART_CATALOG_DEVLOG.md) defines the phase sequence and the exact acceptance criteria per phase.

---

## 13. Glossary

- **CatalogItem** — a row in the `catalog_items` table representing a unique part identity.
- **ConfigurationCustomItem** — a row in the `configuration_custom_items` table representing a user-added, one-off commercial line on a specific configuration.
- **custom_key** — the synthetic `CUSTOM-<uuid8>` identifier of a custom item, used in BOM output as the `part_number` slot.
- **Business key FK** — a foreign key that targets a non-surrogate unique column, in this case `CatalogItem.part_number`. Relies on immutability of the target.
- **OBSOLETE** — lifecycle state of a catalog item that blocks new references but preserves existing ones.
- **FINALIZED snapshot** — self-contained JSON serialization of a `CalculationResponse` stored on the configuration at finalization time; authoritative for FINALIZED reads.
- **Technical BOM / Commercial BOM** — see [ADR_BOM.md](ADR_BOM.md).
- **Reference BOM / CatalogTemplate** — SAP-style design-time boilerplate generator, out of scope here.
- **Promotion** — retroactive classification of a custom item to a later-coded catalog part, out of scope here.
