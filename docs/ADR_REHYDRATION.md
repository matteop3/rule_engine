# ADR: Configuration Re-hydration vs Denormalized Snapshots

## Status

**Amended** (see [Amendment: Hybrid Rehydration](#amendment-hybrid-rehydration-for-finalized-configurations) below)

## Context

When a user saves a configuration, the system needs to decide *what* to persist and *how* to reconstruct the full state on read.

Two approaches exist:

| Approach | What is stored | How state is reconstructed |
|----------|---------------|---------------------------|
| **Re-hydration** (current) | Raw user inputs only (`[{field_id: 1, value: "Pro"}, ...]`) | Rule engine recalculates visibility, availability, validation, and SKU on every read |
| **Denormalized snapshot** | Full computed state (inputs + all derived field states, available options, errors, SKU) | State is returned as-is from the database, no recalculation needed |

## Decision

Configurations store **raw inputs only** (as a JSON array in the `data` column). The full state — field visibility, available options, validation errors, SKU — is **recalculated on every read** by invoking the rule engine against the linked EntityVersion.

## Rationale

1. **Version upgrades work automatically**: When a configuration is upgraded to a newer EntityVersion (`POST /configurations/{id}/upgrade`), the existing inputs are simply re-evaluated against the new version's rules. No data migration or snapshot rebuilding is needed.

2. **Single source of truth**: Rules live in the EntityVersion, not duplicated across every saved configuration. If a rule is corrected in a DRAFT version, previewing a configuration against it immediately reflects the fix.

3. **Storage efficiency**: A configuration with 20 fields stores ~20 key-value pairs instead of a full state object with available options, labels, and metadata for each field.

4. **Simpler write path**: Saving a configuration just persists the inputs and an `is_complete` flag. No need to serialize the entire calculated state.

## Trade-offs

**What this costs:**
- Every read (`GET /configurations/{id}/calculate`) triggers a full rule engine pass — database queries for fields, values, and rules, plus evaluation logic
- If the EntityVersion is modified (only possible in DRAFT status), the same inputs could produce different results at different times

**Why that's acceptable:**
- The data volume per EntityVersion is small (typically dozens of fields, hundreds of rules at most) — recalculation is fast
- PUBLISHED version data (fields, values, rules) is cached in-memory as frozen dataclasses, so repeated calculations for the same version avoid redundant DB queries
- Published versions are immutable, so production configurations always produce consistent results
- The `is_complete` flag is cached on the configuration record to avoid recalculation for list views

## Alternatives Considered

### Full denormalized snapshot

Store the complete `CalculationResponse` (all field states, options, errors) alongside the inputs.

**Rejected**: Creates a consistency problem — if a rule is fixed in a new version, all existing snapshots contain stale data. Upgrading would require re-computing and re-saving every affected configuration. Also increases storage significantly for large entity schemas.

### Hybrid (inputs + cached snapshot)

Store inputs as source of truth, plus a cached snapshot that's invalidated on version changes.

**Rejected**: Adds cache invalidation complexity without a clear performance need. The rule engine is designed for per-request calculation, and the data volumes involved don't justify caching at this stage.

## Cached Derived Values

Two key derived values are cached directly on the Configuration record to avoid recalculation for common operations (list views, SKU lookups):

- **`is_complete`**: Boolean flag indicating whether all required fields are filled and validation passes
- **`generated_sku`**: The SKU string generated from the user's selections and the version's SKU template

Both are recalculated whenever the configuration's data changes (create, update, upgrade) and copied during clone. This is a pragmatic middle ground between pure re-hydration and full snapshot — the most useful derived values are persisted, while the full field state (visibility, available options, validation errors) is still re-hydrated on demand.

## Known Limitations

For FINALIZED configurations, re-hydration of the full field state introduces unnecessary computation: both the inputs and the EntityVersion are immutable at that point, so the calculated state will always be identical.

A natural evolution would be to **snapshot the full computed state at finalization time** — persist the complete `CalculationResponse` alongside the raw inputs when the configuration transitions to FINALIZED. Subsequent reads would return the snapshot directly, bypassing the rule engine entirely.

This optimization is not implemented because the current recalculation cost is negligible at expected scale, but it would be the first thing to address if FINALIZED configurations are read frequently.

## References

- [Configuration calculate endpoint](../app/routers/configurations.py) — re-hydration in `load_and_calculate_configuration`
- [Rule Engine](../app/services/rule_engine.py) — `calculate_state` method
- [Configuration model](../app/models/domain.py) — `data` column (JSON)

---

## Amendment: Hybrid Rehydration for FINALIZED Configurations

### Context

The introduction of the Price List feature adds a mutable data source to the calculation pipeline. Price lists can be updated at any time — prices change, validity dates shift, items are added or removed. This breaks a key assumption underlying pure rehydration: that all data sources feeding the calculation are immutable once a configuration is FINALIZED.

With pure rehydration, a FINALIZED configuration read today could produce different BOM prices than the same read tomorrow, if the price list was modified in between. This violates the guarantee that FINALIZED configurations are immutable snapshots.

Three approaches were considered:

| Approach | Guarantee | Trade-off |
|----------|-----------|-----------|
| **Pure rehydration** (status quo) | None — prices drift with price list edits | Simple, but FINALIZED configs are not truly immutable |
| **Immutable price lists** | Structural — price list locked on first FINALIZED reference | Operational burden: forces creation of new price lists for any price change, even for unrelated products |
| **Snapshot at finalization** | Structural — full calculated state frozen at finalization time | Slightly larger storage per FINALIZED config, but no constraints on price list mutability |

### Decision

FINALIZED configurations store a complete snapshot of the `CalculationResponse` at finalization time. The snapshot is stored in the `snapshot` column (JSON, nullable) on the `Configuration` model.

**Read behavior by status:**

| Configuration status | Read behavior (`GET /configurations/{id}/calculate`) |
|---|---|
| DRAFT | Rehydrate: recalculate from raw inputs, EntityVersion rules, and current price list with `price_date=today` |
| FINALIZED (snapshot present) | Return stored snapshot directly — no rule engine invocation, no database lookups beyond the configuration itself |
| FINALIZED (snapshot absent) | Fall back to rehydration using the stored `price_date` — backward compatibility for configurations finalized before this feature |

**What the snapshot contains** (the full `CalculationResponse`):
- All field states: `current_value`, `available_options`, `is_required`, `is_readonly`, `is_hidden`, `error_message`
- BOM output: technical and commercial trees with resolved prices, `line_total`, `commercial_total`, `warnings`
- `generated_sku` and `is_complete`

**Finalization workflow:**
1. Perform a full recalculation with `price_date=date.today()` and the configuration's `price_list_id`
2. Serialize the `CalculationResponse` via `model_dump(mode="json")`
3. Store the serialized result in `config.snapshot`
4. Save `price_date`, `is_complete`, `generated_sku`, and `bom_total_price` from the fresh calculation
5. Transition status to FINALIZED

### Rationale

The snapshot approach decouples FINALIZED configuration immutability from price list mutability. Price lists remain freely editable — prices can be corrected, future periods can be added, expired items can be cleaned up — without any risk of altering historical FINALIZED documents.

DRAFT configurations continue to use pure rehydration because their purpose is to reflect the current state of all data sources. A DRAFT configuration should always show current prices, current rules, and current field behavior.

The snapshot also eliminates unnecessary computation: both the inputs and the EntityVersion are immutable for FINALIZED configurations, so recalculating the same result on every read adds latency without value.

### Consequences

- FINALIZED configuration reads are faster (no rule engine pass, no price list lookup)
- Price list modifications cannot retroactively alter FINALIZED documents
- Storage increases slightly per FINALIZED configuration (one JSON column with the full calculated state)
- The `snapshot` column is nullable for backward compatibility — configurations finalized before this feature fall back to rehydration
