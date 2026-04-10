# Price List Feature Analysis

## Status

**Approved** (2026-04-08)

## Motivation

The current BOM implementation stores `unit_price` directly on the `BOMItem` table. This design has fundamental limitations:

1. **No centralization**: the same `part_number` across different EntityVersions carries independent prices. Updating a price requires editing every version that uses it.
2. **No temporal tracking**: there is no way to know which price was effective when a configuration was finalized.
3. **No time-based validity**: preparing a 2027 price list that takes effect on January 1st requires manually editing prices on that day.
4. **Consistency workaround**: the current HTTP 409 validation (same `part_number` must have same `unit_price` within a version) exists only because there is no single source of truth.

The `ADR_BOM.md` already anticipated this evolution:
> "A future centralized BOM catalog/price list is planned to replace per-item pricing entirely."

This document formalizes the design decisions for the Price List feature.

---

## Design Decisions

### 1. Global Price List (not tied to Entity or EntityVersion)

Price lists are standalone entities, decoupled from any specific Entity or EntityVersion. The `part_number` is the natural lookup key between the BOM and the price list. An EntityVersion "consumes" a price list; it does not "own" it. This enables reuse across products and versions.

### 2. Temporal Validity as Versioning (no version number on items)

Price list items use `valid_from` / `valid_to` date ranges instead of explicit version numbers. To change a price, you create a new row with a different date range and new price. The old row remains with the old price and old dates.

**No-overlap constraint**: for a given `(price_list_id, part_number)`, no two rows may have overlapping date ranges. This is enforced at CRUD time.

**`valid_to` is mandatory**, with a default of `9999-12-31` (SAP convention). This simplifies overlap checks (every range has two finite endpoints) and avoids null-handling edge cases in SQL. Semantically, `9999-12-31` means "valid indefinitely".

Example:
| part_number | unit_price | valid_from | valid_to |
|---|---|---|---|
| BOLT-M8 | 0.50 | 2026-01-01 | 2026-06-30 |
| BOLT-M8 | 0.55 | 2026-07-01 | 9999-12-31 |

### 3. Graceful Price Resolution (partial total + warnings)

When a BOM item's `part_number` has no valid price in the selected price list at the given date:

- `unit_price = null` for that line item
- `line_total = null` for that line item
- `commercial_total` = sum of all non-null `line_total` values (partial total, not null)
- `is_complete = false` (the configuration cannot be finalized)
- A warning is added to `BOMOutput.warnings` (a new `list[str]` field)

**Warning messages are differentiated** to aid debugging:
- Part number not found: `"Part 'XYZ-999' not found in price list 'Listino 2026'"`
- Part number found but no valid price at date: `"Part 'BOLT-M8' has no valid price at date 2026-03-15 in price list 'Listino 2026'"`

**Why partial total instead of null total**: `is_complete = false` already gates finalization. A partial total gives the user feedback on the order of magnitude during drafting. A null total for a 25,000 EUR configuration missing a 0.50 EUR bolt price is disproportionately uninformative.

**Price override (manual price entry) is out of scope.** It belongs to the discount/commercial workflow feature, planned separately. The price list is the single source of truth.

### 4. Clean Migration (remove `unit_price` from BOMItem)

This is a greenfield project with no production data to preserve. The migration:
- Adds `PriceList` and `PriceListItem` tables
- Adds `price_list_id` and `price_date` columns to `Configuration`
- Removes `unit_price` from `BOMItem`
- Removes the commercial price consistency validation (`_validate_commercial_price_consistency`)
- Removes the `_validate_pricing_by_type` check that required COMMERCIAL items to have `unit_price`

After migration, COMMERCIAL BOM items no longer carry pricing data. Pricing is resolved exclusively from the price list at calculation time.

### 5. Price List Selection (`price_list_id` mandatory, `price_date` optional)

**`price_list_id`** is a mandatory parameter in the `CalculationRequest`. The client must always specify which price list to use. There is no default price list — "default" would be arbitrary when price lists can represent different markets, channels, or product lines.

**`price_date`** is an optional parameter (default: today). It enables:
- Future price simulation ("how much would this cost in January?")
- Historical price lookup ("what was the price when this config was created?")
- Testing future price lists by AUTHOR/ADMIN

Both parameters are also accepted on the stateless `POST /engine/calculate` endpoint with the same validation rules.

**No RBAC restriction on `price_date`**: all roles can use any date. The protection against abuse is at finalization time (see decision #8).

### 6. RBAC: ADMIN and AUTHOR

Price list management (CRUD on both `PriceList` and `PriceListItem`) follows the same RBAC pattern as entities, versions, fields, and rules: ADMIN and AUTHOR roles only. No new role is introduced.

### 7. Price List Header Validity (bounding box for items)

The price list header has mandatory `valid_from` and `valid_to` fields. These serve two purposes:

1. **Selectability**: the `GET /price-lists?valid_at=` endpoint filters by header validity. The frontend uses this to populate the price list dropdown.
2. **Bounding box**: item validity dates must fall within the header's range. `item.valid_from >= header.valid_from` and `item.valid_to <= header.valid_to`. This is enforced at CRUD time.

**No `status` field on the header.** The validity dates are sufficient:
- `valid_from` in the future = "not yet active" (effectively a draft)
- `valid_from <= today <= valid_to` = "active"
- `valid_to` in the past = "expired/archived"

Adding a status enum would create ambiguity when status and dates disagree.

### 8. Finalization: Always Recalculate with `price_date = today`

When a configuration is finalized (`POST /configurations/{id}/finalize`), the system recalculates with `price_date = now()`, regardless of any `price_date` used during drafting. This prevents users from finalizing with stale or advantageous historical prices.

The effective `price_date` at finalization is saved on the Configuration record for audit purposes.

**Price lock** (finalizing with a locked historical price) is out of scope. It requires validity periods, approval workflows, and discount management — all part of the commercial workflow feature.

### 9. Deletion Protection for FINALIZED References

A price list referenced by any FINALIZED configuration cannot be deleted (HTTP 409). This preserves audit traceability: "which price list was used for this offer?"

- Price lists referenced only by DRAFT configurations: deletable. The FK uses `SET NULL`, so the DRAFT's `price_list_id` becomes null. The next calculate returns 422 "price_list_id required".
- Price lists not referenced by any configuration: deletable (hard delete).

**Modifications to price list data (prices, dates) are freely allowed**, even if the price list is referenced by FINALIZED configurations. This is safe because FINALIZED configurations use snapshots (see decision #17).

### 10. No Caching for Price Lists

Price lists are mutable (items can be added, prices changed, dates adjusted). They are not cached in the in-memory TTL cache used for PUBLISHED EntityVersion data (which is immutable). Price list data is queried from the database on every calculation.

If this becomes a bottleneck, a dedicated short-TTL cache can be introduced later.

### 11. Stateless Endpoint

`POST /engine/calculate` accepts the same `price_list_id` and `price_date` parameters with the same validation rules. Since there is no persisted configuration, there is no ambiguity.

### 12. BOM and Price List Independence

BOM item definitions and price list items are independent entities. An AUTHOR can create a BOM item with any `part_number` without it existing in any price list. Validation happens at **calculation time**, not at CRUD time. This avoids:
- Circular dependencies (can't define the product without prices, can't price without the product)
- Temporal coupling (must populate price list before modeling the product)

### 13. Clone/Upgrade Inherits `price_list_id`

When a configuration is cloned or upgraded:
- The new DRAFT configuration inherits `price_list_id` from the source
- The next calculate uses `price_date = today` (it's a DRAFT)
- If the inherited price list is expired, the calculate returns 422 — the user must select a valid price list

This is informative (the user knows which price list was used originally) without being restrictive (they can change it).

### 14. Full CRUD for Price Lists

Endpoint set:

| Method | Endpoint | Description |
|---|---|---|
| GET | `/price-lists` | List price lists (filter: `?valid_at=`, default today) |
| POST | `/price-lists` | Create price list |
| GET | `/price-lists/{id}` | Get price list detail |
| PATCH | `/price-lists/{id}` | Update price list header |
| DELETE | `/price-lists/{id}` | Delete (if not referenced by FINALIZED) |
| GET | `/price-list-items?price_list_id={id}` | List items |
| POST | `/price-list-items` | Create item |
| PATCH | `/price-list-items/{id}` | Update item |
| DELETE | `/price-list-items/{id}` | Delete item |

### 15. FINALIZED Protection via Snapshot

FINALIZED configurations store a complete snapshot (see decision #17). This makes modifications to the price list safe — they cannot retroactively change finalized documents. The only protection enforced on the price list is **deletion prevention** for audit/traceability.

### 16. Item Dates Default from Header

When creating a `PriceListItem`, `valid_from` and `valid_to` default to the parent price list's dates. The AUTHOR can restrict (narrow) the range but cannot exceed the header's bounding box.

### 17. Hybrid Rehydration (DRAFT = rehydrate, FINALIZED = snapshot)

The introduction of the price list creates a mutable data source for calculation. This breaks the assumption underlying pure rehydration (all sources are immutable for PUBLISHED/FINALIZED).

**The solution**: FINALIZED configurations store a complete snapshot of the `CalculationResponse` at finalization time. Subsequent reads return the snapshot directly, bypassing the rule engine.

| Configuration status | Read behavior |
|---|---|
| DRAFT | Rehydrate: recalculate from raw inputs, EntityVersion, and price list |
| FINALIZED | Snapshot: return stored `CalculationResponse` as-is |

**What is snapshotted** (the full `CalculationResponse`):
- Field states: `current_value`, `available_options`, `is_required`, `is_readonly`, `is_hidden`, `error_message`
- BOM output: technical and commercial BOM with resolved prices, `line_total`, `commercial_total`, `warnings`
- `generated_sku`, `is_complete`

A new `snapshot` column (JSON, nullable) is added to the `Configuration` model. It is `null` for DRAFT configurations and populated at finalization time.

**Why snapshot `available_options` too**: even though the EntityVersion is immutable, the snapshot makes the FINALIZED configuration entirely self-contained — no external dependencies for reads, optimal read performance, and resilient to any future feature that might make options dynamic.

This approach is documented in a revision of `ADR_REHYDRATION.md`.

### 18. Seed Data Update

`seed_data.py` must be updated to:
- Create a demo price list with validity dates
- Create price list items for all COMMERCIAL BOM part numbers
- Remove `unit_price` from BOM item creation
- Pass `price_list_id` and `price_date` where applicable

### 19. API Response Schema (no breaking change)

`BOMLineItem` in the calculation response retains `unit_price` and `line_total` fields. The values now come from the price list instead of the BOM item. The client does not know or need to know the source — the response contract is unchanged.

`BOMOutput` gains a new `warnings: list[str]` field (default empty list).

### 20. Audit Trail

Both `PriceList` and `PriceListItem` use the `AuditMixin` (`created_at`, `updated_at`, `created_by_id`, `updated_by_id`). This tracks who changed a price and when — essential for commercial audit.

### 21. FK `price_list_id` with SET NULL on Delete

The `price_list_id` foreign key on `Configuration` uses `SET NULL` on delete. This applies only to DRAFT configurations (FINALIZED configurations block the delete entirely via application-level validation). A DRAFT with `price_list_id = null` receives 422 on the next calculate, prompting the user to select a valid price list.

---

## Domain Model Changes

### New Tables

```
PriceList
├── id (int PK)
├── name (string, unique)
├── description (text, nullable)
├── valid_from (date, required)
├── valid_to (date, required, default 9999-12-31)
├── + AuditMixin

PriceListItem
├── id (int PK)
├── price_list_id (int FK → PriceList)
├── part_number (string)
├── description (text, nullable)
├── unit_price (Numeric(12,4), required)
├── valid_from (date, default from header)
├── valid_to (date, default from header)
├── + AuditMixin
│
├── Constraint: no overlap for (price_list_id, part_number)
├── Constraint: valid_from >= header.valid_from
└── Constraint: valid_to <= header.valid_to
```

### Modified Tables

**BOMItem**: remove `unit_price` column.

**Configuration**: add `price_list_id` (FK → PriceList, nullable, SET NULL on delete), `price_date` (date, nullable), `snapshot` (JSON, nullable).

### ER Additions

```
PriceList ||--o{ PriceListItem : "contains"
Configuration }o--o| PriceList : "uses"
```

---

## Evaluation Waterfall (updated)

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
10. PRICING       → resolve prices from price list, compute totals, generate warnings
```

Step 10 is new. It runs after BOM inclusion/quantity resolution and before returning the response.

---

## Out of Scope

These are explicitly deferred to future development:

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

---

## Impact Summary

| Area | Impact |
|---|---|
| Models | 2 new tables, 3 columns added to Configuration, 1 column removed from BOMItem |
| Schemas | New schemas for PriceList/PriceListItem, modified CalculationRequest, BOMOutput, Configuration schemas |
| Routers | 2 new routers (price_lists, price_list_items), modified configurations and engine routers |
| Services | Modified rule_engine.py (price resolution logic), modified versioning.py (clone cleanup) |
| Cache | Modified CachedBOMItem (remove unit_price) |
| Tests | ~975+ existing tests to update (BOM tests need price list setup), ~200+ new tests |
| Seed data | Full rewrite of BOM and configuration sections |
| Documentation | README, ADR_REHYDRATION, ADR_BOM, TESTING.md |
