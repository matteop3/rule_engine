# ADR: Price List

## Status

**Accepted**

## Context

Product configurators need to attach prices to the commercial side of the BOM. Two approaches exist:

1. **Per-item pricing**: store `unit_price` directly on each `BOMItem` row.
2. **Centralized price list**: store prices in a dedicated catalog, looked up at calculation time by `part_number`.

Per-item pricing has fundamental limitations:

- **No centralization**: the same `part_number` across different EntityVersions carries independent prices. Updating a price requires editing every version that uses it.
- **No temporal tracking**: there is no way to know which price was effective when a configuration was finalized.
- **No time-based validity**: preparing a future price list that takes effect on a given date requires manual editing on that day.
- **Consistency workaround**: HTTP 409 validation enforcing the same `unit_price` for repeated `part_number`s within a version exists only because there is no single source of truth.

`ADR_BOM.md` already anticipated this evolution with an explicit note that a centralized catalog would replace per-item pricing.

## Decisions

### 1. Global price list (not tied to Entity or EntityVersion)

Price lists are standalone entities, decoupled from any specific Entity or EntityVersion. The `part_number` is the natural lookup key between the BOM and the price list. An EntityVersion consumes a price list; it does not own it. This enables reuse across products, versions, and markets.

### 2. Temporal validity via date ranges, not version numbers

Price list items use `valid_from` / `valid_to` date ranges. To change a price, a new row is created with a new date range. The old row remains with the old price and old dates.

**No-overlap constraint**: for a given `(price_list_id, part_number)`, no two rows may have overlapping date ranges. Enforced at CRUD time.

**`valid_to` is mandatory**, with a default of `9999-12-31` (SAP convention). Every range has two finite endpoints — no null-handling edge cases in SQL or application code. Semantically, `9999-12-31` means "valid indefinitely".

Example:

| part_number | unit_price | valid_from | valid_to |
|---|---|---|---|
| BOLT-M8 | 0.50 | 2026-01-01 | 2026-06-30 |
| BOLT-M8 | 0.55 | 2026-07-01 | 9999-12-31 |

### 3. Price list header as bounding box

The header has mandatory `valid_from` / `valid_to` fields. They serve two purposes:

1. **Selectability**: `GET /price-lists?valid_at=` filters by header validity for dropdown population.
2. **Bounding box**: item dates must satisfy `item.valid_from >= header.valid_from` and `item.valid_to <= header.valid_to`. Enforced at CRUD time.

No `status` field on the header — the dates already express lifecycle (`valid_from` in the future = not yet active; `valid_from <= today <= valid_to` = active; `valid_to` in the past = expired). Adding a status enum would create ambiguity when status and dates disagree.

### 4. Graceful price resolution (partial total + warnings)

When a BOM item's `part_number` has no valid price at the given date:

- `unit_price = null` and `line_total = null` for that line
- `commercial_total` = sum of all non-null line totals (partial total, not null)
- `is_complete = false` (the configuration cannot be finalized)
- A warning is added to `BOMOutput.warnings` (a new `list[str]` field, default `[]`)

Warning messages are differentiated to aid debugging:

- Part number not found: `"Part 'XYZ-999' not found in price list 'Listino 2026'"`
- Part number found but no valid price at date: `"Part 'BOLT-M8' has no valid price at date 2026-03-15 in price list 'Listino 2026'"`

**Why partial total instead of null total**: `is_complete = false` already gates finalization. A partial total gives the user feedback on the order of magnitude during drafting. A null total for a 25,000 EUR configuration missing a 0.50 EUR bolt is disproportionately uninformative.

### 5. `price_list_id` mandatory, `price_date` optional

`price_list_id` is mandatory in the `CalculationRequest`. The client must always specify which price list to use — there is no default. "Default" would be arbitrary when price lists can represent different markets, channels, or product lines.

`price_date` is optional (default: today). It enables future price simulation, historical lookups, and testing future price lists. No RBAC restriction applies to `price_date` — the protection against abuse sits at finalization time (see decision #8).

Both parameters are also accepted on the stateless `POST /engine/calculate` endpoint with the same validation rules.

### 6. Item dates default from header

When creating a `PriceListItem`, `valid_from` and `valid_to` default to the parent price list's dates. The AUTHOR can narrow the range but cannot exceed the header's bounding box.

### 7. BOM and price list independence

BOM item definitions and price list items are independent entities. An AUTHOR can create a BOM item with any `part_number` without that part existing in any price list. Validation happens at **calculation time**, not at CRUD time. This avoids:

- Circular dependencies (can't define the product without prices, can't price without the product)
- Temporal coupling (must populate price list before modeling the product)

### 8. Finalization always recalculates with `price_date = today`

When a configuration is finalized, the system recalculates with `price_date = today`, regardless of any `price_date` used during drafting. This prevents users from finalizing with stale or advantageous historical prices. The effective `price_date` is saved on the Configuration record for audit purposes.

**Price lock** (finalizing with a locked historical price) is out of scope. It requires validity periods, approval workflows, and discount management — all part of a commercial workflow feature.

### 9. Deletion protection for FINALIZED references

A price list referenced by any FINALIZED configuration cannot be deleted (HTTP 409). This preserves audit traceability.

- Price lists referenced only by DRAFT configurations: deletable. The FK uses `SET NULL`, so the DRAFT's `price_list_id` becomes null. The next calculate returns 422 "price_list_id required".
- Price lists not referenced by any configuration: deletable (hard delete).

**Modifications to price list data** (prices, dates) are freely allowed even when referenced by FINALIZED configurations. This is safe because FINALIZED configurations store a snapshot (see [ADR: Re-hydration](ADR_REHYDRATION.md)).

### 10. No caching for price lists

Price lists are mutable (items can be added, prices changed, dates adjusted). They are not cached in the in-memory TTL cache used for PUBLISHED EntityVersion data, which is immutable. Price list data is queried from the database on every calculation. If this becomes a bottleneck, a dedicated short-TTL cache can be introduced later.

### 11. Clone / upgrade inherits `price_list_id`

When a configuration is cloned or upgraded, the new DRAFT inherits `price_list_id` from the source. The next calculate uses `price_date = today` (it is a DRAFT). If the inherited price list is expired, the calculate returns 422 — the user must select a valid price list. Informative without being restrictive.

### 12. RBAC: ADMIN and AUTHOR

Price list management (CRUD on both `PriceList` and `PriceListItem`) follows the same RBAC pattern as entities, versions, fields, and rules: ADMIN and AUTHOR roles only. No new role is introduced.

### 13. `BOMItem.unit_price` removed

The column is removed from the model. Pricing is resolved exclusively from the price list at calculation time. The CRUD validations `_validate_pricing_by_type` and `_validate_commercial_price_consistency` are deleted.

COMMERCIAL BOM items no longer carry pricing data. The response schema `BOMLineItem` retains `unit_price` and `line_total`; the values now come from the price list. The client does not know or need to know the source — the response contract is unchanged.

### 13a. `PriceListItem.description` superseded by the catalog

The `description` column on `PriceListItem` is superseded by `CatalogItem.description`. A price list item no longer carries its own description; `PriceListItem.part_number` is a foreign key to `CatalogItem.part_number`, and the canonical description is joined through the catalog. CRUD validation rejects price list items that reference a missing or `OBSOLETE` catalog entry. See [ADR: Catalog Item](ADR_CATALOG_ITEM.md) for the full design.

### 14. `BOMOutput.warnings` is additive

`BOMOutput` gains a new `warnings: list[str]` field with an empty list default. Existing clients that ignore unknown fields continue to work; clients that surface warnings can read the new field.

### 15. Evaluation waterfall: pricing step added after BOM

```
1.  VISIBILITY    → is the field shown?
2.  CALCULATION   → is the value system-determined?
3.  EDITABILITY   → is the field readonly?
4.  AVAILABILITY  → which options are available?
5.  MANDATORY     → is the field required?
6.  VALIDATION    → is the value valid?
7.  Completeness  → are all required fields filled?
8.  SKU           → generate product code
9.  BOM           → evaluate inclusion, resolve quantities
10. PRICING       → resolve prices from price list, compute totals, emit warnings
```

Step 10 runs after BOM inclusion/quantity resolution and before returning the response.

### 16. Audit trail via `AuditMixin`

Both `PriceList` and `PriceListItem` use `AuditMixin` (`created_at`, `updated_at`, `created_by_id`, `updated_by_id`). This tracks who changed a price and when — essential for commercial audit.

## Consequences

- **Positive**: single source of truth for prices, usable across products and versions.
- **Positive**: temporal validity enables future price planning and historical lookups without data migrations.
- **Positive**: BOM item CRUD is simpler — no pricing fields, no pricing validations.
- **Positive**: FINALIZED configurations remain fully immutable via the snapshot mechanism; price list mutability does not leak into historical documents.
- **Negative**: calculation now requires a mandatory `price_list_id` parameter — clients must explicitly select a price list.
- **Negative**: `POST /engine/calculate` and `GET /configurations/{id}/calculate` can fail with 422 if the selected price list is expired or missing.
- **Negative**: price list data is not cached; every calculation queries the database. Acceptable at current scale.

## Out of Scope

| Feature | Rationale |
|---|---|
| Cost price / landed cost | Part of cost management, not sales pricing |
| Discount tiers / customer-specific discounts | Part of commercial workflow |
| Margins / markup calculation | Part of commercial workflow |
| Multi-currency | A `currency` field on the header can be added later without breaking changes |
| Price override on configuration | Part of commercial workflow (explicit, tracked, requires RBAC) |
| Price lock at finalization | Requires validity periods, approval workflows — part of commercial workflow |
| Approval workflows on price lists | Not needed without multi-user pricing governance |
| Granular audit log (old/new value tracking) | Cross-cutting concern, not specific to price lists |

## Known Gaps and Follow-ups

These are not blocking issues for the current release, but are explicitly acknowledged for future work.

### Snapshot schema versioning

The FINALIZED `snapshot` column stores the JSON serialization of the Pydantic `CalculationResponse` (and its nested `BOMOutput`, `BOMLineItem`, etc.). The shape is dictated by the Python models, not by the EntityVersion — so EntityVersion immutability does not protect against schema drift. If a future change renames, adds, removes, or retypes a field in those models, existing snapshots written under the old shape will fail Pydantic validation on read.

A cheap mitigation is to embed an explicit `schema_version` key in the serialized payload now (e.g. `schema_version: 1`). The read path can then branch on the version and invoke a `_migrate_snapshot_vN_to_vN_plus_1` helper when the model changes, instead of forcing a one-shot DB migration or accepting data loss.

### Bulk import of price list items

Real-world price catalogs routinely contain hundreds or thousands of rows. The current CRUD surface exposes only one-item-at-a-time endpoints, and the no-overlap check runs linearly per insert. This is sufficient for demos and tests but becomes impractical the first time a real catalog is loaded. A bulk import endpoint (CSV or JSON, validated and persisted in a single transaction) is a known follow-up.

### Timezone semantics of `price_date = today`

`date.today()` resolves against the server's local timezone. If the application runs in UTC while users operate in a different zone, there is a window around local midnight in which "today-server" and "today-user" disagree. For price lists that take effect on a specific date, two users calculating at nearly the same moment can observe different prices. The authoritative timezone (server, user, or business) should be chosen explicitly and documented; the current implementation implicitly uses the server.

### Optimistic locking (cross-cutting, not price-list-specific)

No mutable resource in the application (price lists, items, DRAFT configurations, DRAFT entities, rules, etc.) currently exposes optimistic locking. Two users who open the same record, edit it concurrently, and save in sequence will silently overwrite each other ("last write wins"). For audit-sensitive areas such as price lists the risk is tangible. The standard remedy — expose `updated_at` as an ETag on GET, require it in `If-Match` on PATCH/DELETE, return 412 on mismatch — is a cross-cutting enhancement rather than a price-list-specific one, and is noted here because pricing is the first area where the lack is materially visible.

## Related

- [ADR: BOM Generation](ADR_BOM.md) — BOM structure and the pricing amendment (decisions #1 and #7)
- [ADR: Re-hydration](ADR_REHYDRATION.md) — Hybrid rehydration that keeps FINALIZED configurations immutable despite mutable price lists
- [ADR: Catalog Item](ADR_CATALOG_ITEM.md) — Canonical part identity and metadata; supersedes `PriceListItem.description`
