# ADR: Configuration Custom Items

## Status

**Accepted**

## Context

The catalog (see [ADR: Catalog Item](ADR_CATALOG_ITEM.md)) closes the door on free-string part numbers: every `BOMItem` and `PriceListItem` references a catalog entry by immutable `part_number`. That is the right default for parts that production and accounting both understand.

But commercial quoting regularly needs lines that never go through engineering:

- A one-off on-site install, a rush-delivery fee, a sample signage package, a bundled service hour.
- Parts that will eventually be codified but are not yet — the sales team needs to close today, not next quarter.
- Content visible to the customer on a quote but irrelevant to the production BOM.

Forcing these through the catalog creates phantom master-data (transient fees appearing as ACTIVE parts forever) and creates friction every time a sales user wants to add a custom line. The industry workaround — SAP's "text items", NetSuite's "description-only items", CPQ's "custom line" — sits next to the master-data catalog, not inside it.

The design question is not *whether* to allow such lines but *where* they live and how they interact with the rest of the pipeline. Options:

1. A free-string escape hatch on `BOMItem` that disables catalog validation when a flag is set.
2. A dedicated per-configuration table, with its own identifier, scoped to the commercial output only.

Option 1 pollutes the BOM table with two separate semantics. Option 2 keeps the catalog invariant intact and localizes the escape hatch to the place it actually belongs — the configuration.

Key design questions addressed here:

1. Where are custom items stored, and at what scope?
2. How are they identified, and how stable is that identity?
3. What value constraints apply, and where are they enforced?
4. How do they enter the calculation response?
5. What semantics apply on clone, upgrade, and finalize?
6. How is future retroactive classification ("promotion" to a catalog part) kept as a possible additive follow-up?

## Decisions

### 1. Per-configuration table `configuration_custom_items`

A dedicated SQL table tied to `configurations` via FK, `ON DELETE CASCADE`. Custom items have no identity outside a configuration and are deleted when the parent configuration is hard-deleted.

- `configuration_id UUID NOT NULL` — FK to `configurations.id`.
- `custom_key VARCHAR(20) NOT NULL UNIQUE` — server-generated identifier (see decision #2).
- `description TEXT NOT NULL` — free text, required, non-empty after strip.
- `quantity NUMERIC(12,4) NOT NULL` with `CHECK (quantity > 0)`.
- `unit_price NUMERIC(12,4) NOT NULL` with `CHECK (unit_price >= 0)`.
- `unit_of_measure VARCHAR(20) NULLABLE` — optional; custom lines often have no formal UoM.
- `sequence INTEGER NOT NULL DEFAULT 0` — ordering within a configuration's custom block.
- `AuditMixin` columns (`created_at`, `updated_at`, `created_by_id`, `updated_by_id`) — answer "who added this uncoded line worth €5000?".

The table is its own concern. `BOMItem` stays catalog-only.

### 2. Server-generated `custom_key` of the form `CUSTOM-<uuid8>`

`custom_key` is assigned by the server as `f"CUSTOM-{uuid.uuid4().hex[:8]}"` (e.g. `CUSTOM-a3f91b07`). It is opaque, fixed-width (15 characters), and unique at the DB level.

- Clients **cannot** provide `custom_key` on create — it is stripped silently from the payload before write.
- Clients **cannot** modify `custom_key` on update — presence in the `PATCH` body raises HTTP 422 with an explicit message.
- The key is used as the `part_number` slot in the calculation output, so the commercial line shape is uniform between catalog-sourced and custom rows.

The key is stable forever. Collisions are astronomically unlikely in practice (8 hex chars = ~4.3B space, scoped by unique constraint), and collision-on-insert is rejected by the DB. The stability is the anchor for the `CustomItemPromotion` follow-up (see Known Gaps) — a promotion table can `JOIN ON custom_key` safely only if the key never mutates.

### 3. Value constraints enforced at both the DB and Pydantic layers

The constraints live in two places, not one:

- **Database**: named `CHECK` constraints (`ck_cci_quantity_positive`, `ck_cci_unit_price_nonnegative`) reject invalid writes at the storage boundary, so a bypass of the API cannot produce corrupt rows.
- **Pydantic**: `quantity = Field(..., gt=0)`, `unit_price = Field(..., ge=0)`, and a `description` validator that strips whitespace and rejects empty strings with HTTP 422.

Both are load-bearing. The DB catches anything that sidesteps the API; the Pydantic layer produces user-friendly 422 responses with field-level detail. Neither layer alone is sufficient.

`unit_price = 0` is valid — a $0 commercial line appears on the quote for a free add-on. Negative values are rejected (neither the DB nor the schema allows them).

### 4. Commercial-only, no technical equivalent

Custom items appear **only** in the commercial BOM output. They are never emitted into the technical BOM.

- If a part is not in the catalog, production does not know what to build. A technical custom line would be a promise the company cannot keep.
- Engineering BOM semantics (hierarchy, sub-assemblies, production quantities, conditional inclusion) do not apply to a one-off quote line.

Custom lines are flat: no `parent_bom_item_id`, no children, no conditional-inclusion rules, no availability gating. They are emitted as root-level commercial lines with `bom_type="COMMERCIAL"`.

### 5. Nested CRUD under `/configurations/{id}/custom-items`

| Method | Path | Roles | Description |
|---|---|---|---|
| `GET` | `/configurations/{id}/custom-items` | owner + ADMIN | List for this configuration, ordered by `(sequence, id)`. |
| `POST` | `/configurations/{id}/custom-items` | owner + ADMIN | Create. DRAFT only. Server generates `custom_key`. |
| `PATCH` | `/configurations/{id}/custom-items/{item_id}` | owner + ADMIN | Update `description`, `quantity`, `unit_price`, `unit_of_measure`, `sequence`. DRAFT only. `custom_key` immutable. |
| `DELETE` | `/configurations/{id}/custom-items/{item_id}` | owner + ADMIN | Delete. DRAFT only. |

**Ownership:** a USER can manipulate custom items only on configurations they own. ADMIN can act on any configuration. This mirrors the existing pattern on `/configurations/{id}/*` endpoints — custom items inherit their parent's authorization model rather than introducing a dedicated one.

**DRAFT gating:** all mutations require `Configuration.status == DRAFT`. FINALIZED configurations return HTTP 409 on create/update/delete, consistent with the global FINALIZED immutability rule.

### 6. Engine integration: CUSTOM step appended after PRICING

The rule engine gains one step at the end of the BOM pipeline:

```
 9. BOM        → evaluate inclusion, resolve quantities
10. PRICING    → resolve catalog prices, compute catalog totals, emit warnings
11. CUSTOM     → append custom items from the configuration, add to commercial total
```

Mechanics:

- The engine loads `ConfigurationCustomItem` rows for the current configuration at calculation time — only when the calculation has a `configuration_id`. The stateless `POST /engine/calculate` endpoint has no configuration and skips the CUSTOM step entirely.
- For each custom row, a `BOMLineItem` is emitted with: `part_number = custom_key`, `description = row.description`, `category = None`, `unit_of_measure = row.unit_of_measure`, `quantity = row.quantity`, `unit_price = row.unit_price`, `line_total = quantity * unit_price`, `bom_item_id = None`, `is_custom = True`, `bom_type = "COMMERCIAL"`.
- Custom lines append **after** all catalog-sourced commercial lines, preserving `sequence` within the custom block.
- `commercial_total` becomes `sum(catalog line totals with valid price) + sum(custom line totals)`. When the entity has no BOM output at all, `commercial_total` starts at `None` and becomes the sum of custom totals only.
- Custom items **never** emit warnings. By construction they carry their own price; there is nothing to look up and nothing to fail gracefully.
- Custom items **never** affect `is_complete`. Completeness is determined exclusively by catalog-line pricing (partial-total + warnings), mandatory fields, and validation. Adding or removing a custom line cannot block or unblock finalization.

### 7. Schema additions are additive

`BOMLineItem` gains two fields:

- `is_custom: bool = False` — defaults to `False`, so catalog-sourced lines serialize unchanged. Custom lines set it to `True`, giving clients a stable flag to style or filter custom rows.
- `bom_item_id: int | None = None` — relaxed from required `int`. Catalog lines continue to populate it; custom lines carry `None` since they have no `BOMItem` row to reference.

`CalculationRequest` gains `configuration_id: str | None = None`, populated automatically by the configuration-scoped calculate helper and absent on stateless `/engine/calculate` calls.

All three changes are additive: existing clients that ignore unknown fields continue to work, and `bom_item_id` remains populated for every line clients currently read.

### 8. Clone copies custom items with fresh keys

When a configuration is cloned (DRAFT → new DRAFT, FINALIZED → new DRAFT), every `ConfigurationCustomItem` row is copied to the new configuration. Each copy receives a **new** `custom_key` — the source and clone key sets are disjoint.

The content fields (`description`, `quantity`, `unit_price`, `unit_of_measure`, `sequence`) are preserved verbatim. `created_by_id` is set to the cloning user — the clone is their action. `AuditMixin` timestamps are fresh.

Preserving the lines (and letting the user remove what they don't want) is safer than dropping them silently. Fresh keys keep future promotions distinguishable between the original quote and the cloned one.

### 9. Upgrade preserves custom items unchanged

When a DRAFT configuration is upgraded to a newer `EntityVersion`, custom items are left alone. They belong to the configuration, not the version — they carry their own description and price and do not reference any field, BOM item, or catalog entry.

Upgrading swaps `entity_version_id` and recalculates. Custom rows survive the swap untouched and appear in the next calculation exactly as before. No code change in the upgrade endpoint is needed to achieve this; it falls out of the table scoping.

### 10. Finalization snapshot is self-contained

At finalization time, the full `CalculationResponse` is serialized into `Configuration.snapshot` as JSON. Custom lines are already part of `BOMOutput.commercial` by the time the snapshot is taken, so they appear in the frozen JSON alongside catalog lines.

After finalization:

- Mutations to the underlying `configuration_custom_items` rows via any path (direct DB write bypassing the API, cascade from some other migration) do **not** alter the FINALIZED read. Reads of FINALIZED configurations return the snapshot, never the live rows.
- Custom-items CRUD is blocked at the router level by the same DRAFT-only gate used for configuration inputs — FINALIZED returns HTTP 409 on create/update/delete.

This is the same immunity mechanism that already protects against post-finalization catalog and price list mutation (see [ADR: Re-hydration](ADR_REHYDRATION.md)). Custom items extend it, not a separate one.

### 11. Stateless `/engine/calculate` stays catalog-only

The stateless endpoint takes a hypothetical `current_state` and returns a calculation without persisting anything. Custom items are tied to a persistent `Configuration` row; they have no sensible representation in a stateless preview. The endpoint remains untouched — custom items are invisible to it.

If a client wants to preview the effect of adding a custom line, the workflow is: create a DRAFT configuration, add the custom item via the nested CRUD, call `/configurations/{id}/calculate`. The cost of creating a DRAFT is cheap and the endpoint is the right abstraction.

### 12. Keys and part numbers share a response slot but are structurally distinguishable

`BOMLineItem.part_number` carries the catalog business key for catalog-sourced lines and the `CUSTOM-<uuid8>` key for custom lines. The slot is shared so clients that render "one commercial BOM table" work unchanged.

For clients that need to distinguish: `is_custom` is the canonical flag, and the `CUSTOM-` prefix on `part_number` is also diagnostic. Clients should prefer `is_custom` (explicit, structural) over prefix-matching on the string (convention-by-accident).

## Consequences

- **Positive**: sales users can add one-off lines without polluting master data. The catalog stays clean.
- **Positive**: custom items inherit the FINALIZED snapshot's immutability for free — no dedicated freeze path.
- **Positive**: clone and upgrade behave intuitively without special-casing by the caller.
- **Positive**: the CUSTOM step is a single conditional append at the end of the pipeline, easy to reason about and easy to skip when not needed (stateless `/engine/calculate`).
- **Positive**: `custom_key` stability keeps the door open for the `CustomItemPromotion` follow-up without forcing any commitment today.
- **Negative**: two payment-line semantics live side-by-side in the commercial BOM output. Clients that want strong type separation must branch on `is_custom`.
- **Negative**: custom items are invisible to BOM-level analytics that aggregate by catalog `part_number`. Intentional — they are not master data.
- **Negative**: creating many custom items per configuration means many audit rows; this is the correct cost for the audit coverage.

## Out of Scope

| Feature | Rationale |
|---|---|
| Technical-BOM custom items | Production needs coded parts. Custom lines are a commercial construct only. |
| Retroactive reclassification of custom items to catalog part numbers | See `CustomItemPromotion` follow-up below. |
| Bulk import of custom items | One-off lines are added per-configuration, by hand. No bulk use case. |
| Cross-configuration custom item reuse ("saved custom templates") | Would reintroduce master-data semantics. Add a catalog entry instead. |
| Discount lines / negative unit price | Discounting is a commercial workflow concern with its own approval model. Out of scope here. |
| Optimistic locking on custom items | Cross-cutting gap (see `ADR_PRICE_LIST.md`), not custom-items-specific. |

## Known Gaps and Follow-ups

### CustomItemPromotion (retroactive reclassification)

**Scenario.** A FINALIZED configuration contains a custom item — say a `CUSTOM-a3f91b07` on-site safety audit. Six months later the business decides to code that service in the catalog as `SVC-SAFETY-AUDIT`. For reporting purposes, the business wants the historical custom line to be attributable to the new catalog code without rewriting the FINALIZED document.

**What it would be.** A separate mapping table `CustomItemPromotion(custom_key, promoted_to_part_number, promoted_at, promoted_by, notes?)`. Reporting queries `LEFT JOIN` on this mapping; queries that read the FINALIZED snapshot continue to see the original document unchanged. It is **classification only, never recalculation**: historical prices are not corrected, totals are not altered, `is_complete` is not touched. Reversible by deleting the promotion row.

**Why the two stability invariants matter now.** For this future mechanism to work additively, two guarantees must already hold in the current design, and they do:

1. **`custom_key` is stable forever** — no reuse, no renumber. Achieved by server-side UUID generation and standard PK-with-audit behavior. The immutability on update (HTTP 422 if present in the `PATCH` body) makes this load-bearing.
2. **`CatalogItem.part_number` is never renamed in place** — the immutability rule in [ADR: Catalog Item](ADR_CATALOG_ITEM.md#4-part_number-is-never-renamed-in-place). The promotion table's `promoted_to_part_number` column would rely on this target being stable.

Both invariants are already core to the current design and documented explicitly. They are not load-bearing *for* this feature, but they keep the door open *for* the future promotion feature.

**Why postponed.** The real design depends on questions that can only be answered with concrete requirements:

- 1-to-1 or 1-to-N promotion? (Can two custom keys promote to the same catalog part?)
- Revocable? (Can a promotion be undone? By whom? With what audit?)
- Fuzzy matching on description? (Heuristic suggestions vs. fully manual curation.)
- Internal reporting only, or exposed to an external data warehouse?
- Does a promotion alter downstream aggregate reports retroactively or only prospectively?

Until there is real demand and real reporting requirements, speculating on the shape would produce the wrong shape. The cost of delay is zero: the feature can be added as a purely additive migration (new table, new read path in reporting queries) when the need emerges.

**Where documented.** Here, in this Known Gaps section. The catalog ADR also references it from its `part_number` immutability decision — the two are paired invariants.

### Bulk operations on custom items

The current CRUD surface is one-item-at-a-time. A sales user adding ten custom lines to a single quote does ten round-trips. This is acceptable for low-volume usage and keeps the validation path simple, but a `POST /configurations/{id}/custom-items/bulk` endpoint taking a list would be a straightforward additive follow-up when the use case demands.

### Localization of custom-item descriptions

Custom item `description` is a single free-text column. If the application grows multi-language UI support (see [ADR: i18n](ADR_I18N.md) for the framework), descriptions would need the same JSONB treatment as other user-facing strings. Out of scope here; aligns with the cross-cutting i18n approach rather than a custom-items-specific one.

## Related

- [ADR: Catalog Item](ADR_CATALOG_ITEM.md) — Canonical part identity; the custom-items feature is the intentional escape hatch the catalog was allowed to be strict because of.
- [ADR: Price List](ADR_PRICE_LIST.md) — Commercial-line pricing framework; custom items live alongside catalog-sourced lines in the same commercial output and share the `commercial_total` slot, without participating in price-list lookup or warnings.
- [ADR: Re-hydration](ADR_REHYDRATION.md) — FINALIZED snapshot immunity; custom-item snapshot behavior reuses the same mechanism that protects against catalog and price list mutation.
- [ADR: BOM Generation](ADR_BOM.md) — Commercial-BOM structure; custom items are flat root-level commercial lines in the same output model.
