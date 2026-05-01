# ADR: Engineering BOM Templates and Materialization

## Status

**Accepted**

## Context

`BOMItem` describes the structure of a single product version: a flat or hierarchical list of part numbers that the engine evaluates against field state on every calculation. That representation is enough for an MVP CPQ scenario, but it leaves three problems unaddressed:

1. **Composite-part authoring is manual.** When `MOUSE-PRO` always contains a cable, a connector, and a housing, an AUTHOR has to enter those four rows by hand on every `EntityVersion` that ships a `MOUSE-PRO`. This is error-prone, duplicative, and hostile to maintenance: a structural change to `MOUSE-PRO` requires walking every version that uses it.
2. **There is no top-down "what materials does this configuration consume?" view.** `BOMOutput.technical` is per-unit-of-parent (stoichiometric); to answer the basic procurement question — "to build one of *this*, how many of *this leaf* do I need?" — clients have to traverse the tree and multiply ancestors themselves.
3. **A latent aggregation bug** orphaned the children of merged sibling `BOMItem` rows, surfacing them as spurious roots in the technical tree.

The engineering BOM feature addresses all three. It introduces an authoring surface above the catalog (the **engineering template**), a materialization service that explodes templates into ordinary `BOMItem` rows on demand, a flat aggregated view (`technical_flat`) computed by the engine on every calculation, and the corrected aggregation algorithm.

The key design questions:

1. Should template explosion be live (engine dereferences at calculation time) or boilerplate-style (one-shot expansion at authoring time)?
2. Where does the template live — its own header table, on `CatalogItem`, or implicit through `EngineeringTemplateItem` rows alone?
3. How are cycles in the template graph prevented?
4. How are pathological expansions bounded?
5. What does the response shape look like, and how does it survive into the FINALIZED snapshot?

## Decisions

### 1. Templates are flat sets of `EngineeringTemplateItem` rows attached to `CatalogItem`

A `CatalogItem`'s engineering template is the set of `EngineeringTemplateItem` rows where `parent_part_number` equals that part. There is no header aggregate (no `EngineeringTemplate` table). Each row describes one direct-child relationship; multi-level structure emerges from recursive composition (decision 4).

**Why no header.** The header would carry no metadata that does not already live on `CatalogItem`. Adding a row to the table = "this composite part exists"; deleting all rows = "this part is a leaf again". Keeping the layer flat makes the catalog the single root of identity and avoids a redundant lifecycle on the template object itself.

### 2. Composite identity is implicit and additive

A `CatalogItem` becomes a "composite part" the moment any `EngineeringTemplateItem` row references it as `parent_part_number`. There is no `is_composite` flag on `CatalogItem`. Removing all template rows under a part returns it to leaf status. The catalog stays oblivious to composition (in line with `ADR_CATALOG_ITEM`'s decision to keep the catalog flat).

### 3. Snap-detach: materialization produces ordinary `BOMItem` rows

When an AUTHOR triggers materialization, the system reads the template, recursively explodes it, and writes ordinary `BOMItem` rows on a target DRAFT `EntityVersion`. After the transaction commits, the produced rows have **no link** to the template; they can be edited, attached `BOMItemRule` rows, deleted, or cloned with the rest of the version using the existing CRUD surface.

**Rationale.** This mirrors the SAP "explode reference BOM into engineering BOM" workflow and keeps `EntityVersion` the sole runtime source of truth for product structure. Templates are a boilerplate generator invoked on demand, not a live composition that the engine dereferences at calculation time. Subsequent template edits do not propagate to already-materialized versions, which is the correct semantics for an authoring-time tool: a quote built last quarter must not change because someone updated the template today.

### 4. Recursive expansion to leaves in a single request

If a child of a template is itself composite (its `part_number` has its own template), the child is exploded too, and so on, down to leaves. The recursion is breadth-then-depth across the template graph, bounded by `MAX_BOM_EXPLOSION_DEPTH=32` and `MAX_BOM_EXPLOSION_NODES=500` (decision 11). A single `POST /bom-items` with `explode_from_template=true` produces the entire hierarchy in one transaction.

### 5. Per-child opt-out: `EngineeringTemplateItem.suppress_child_explosion`

A template author can flag a single edge as "treat this child as opaque". When `suppress_child_explosion=true`, materialization creates the child `BOMItem` with `suppress_auto_explode=true` and **does not recurse into the child's own template**. The author is saying "in *this* kit, the sub-assembly is a leaf — don't expand it further".

### 6. Per-instance opt-out: `BOMItem.suppress_auto_explode`

A flag on the materialized row itself, separate from the template-level opt-out, supports a future re-explode endpoint and gives authors a way to mark "this row stays a leaf even if I re-explode the parent". It has no runtime effect on the calculation engine; it is an authoring-time hint.

### 7. CRUD on template items uses a nested URL under the catalog

Path prefix: `/catalog-items/{part_number}/template`. Reads (`GET .../template`) are open to any authenticated user. Writes (`POST .../template/items`, `PATCH .../template/items/{id}`, `DELETE .../template/items/{id}`) require ADMIN/AUTHOR. List ordering is `(sequence, child_part_number)`.

### 8. Cycle detection on POST and PATCH; advisory lock on every write

Before inserting an edge `(parent, child)`, the service runs a DFS from `child` along the template graph looking for `parent`. If found, the request is rejected with HTTP 409 and a structured payload `{"detail": {"message": ..., "cycle_path": [parent, ..., parent]}}`. Self-loops short-circuit to a length-1 cycle path.

A PostgreSQL transactional advisory lock (`pg_advisory_xact_lock(hashtext('engineering_template_graph'))`) is acquired on every POST/PATCH/DELETE for symmetry. Without it, two concurrent inserts could each see a safe graph in isolation and together close a cycle (`T1: A→B`, `T2: B→A`). The lock serializes mutations cluster-wide; reads do not acquire it.

### 9. Immutable graph endpoints

`PATCH .../template/items/{id}` allows mutation of `quantity`, `sequence`, `suppress_child_explosion` only. Payloads carrying `parent_part_number` or `child_part_number` are rejected at the schema layer with HTTP 422. Topology changes go through DELETE + POST; this avoids re-running cycle detection on every PATCH and matches `CatalogItem.part_number`'s "obsolete and re-create" idiom.

### 10. UNIQUE on `(parent_part_number, child_part_number)`

A given child can appear at most once in a given parent's template. Duplicate inserts return HTTP 409 with an explanatory message. The constraint is enforced at the database level and pre-checked at the service level (under the advisory lock) to produce a clear error before relying on the DB.

### 11. Operational limits: depth and node count

Two configurable settings (`app/core/config.py`) gate every recursive expansion:

| Setting (env) | Default | Meaning |
|---|---|---|
| `MAX_BOM_EXPLOSION_DEPTH` | 32 | Maximum recursion depth. The root is at depth 0; a leaf one level down is at depth 1. |
| `MAX_BOM_EXPLOSION_NODES` | 500 | Maximum total nodes (root + descendants) produced by one materialization or preview. |

Breach raises `ExplosionLimitExceededError(limit_name, max_value, reached)`, which the routers convert into HTTP 413 with the payload `{"limit": ..., "max": ..., "reached": ...}`. The check exists as a runtime safety net: even if the cycle detector ever fails to prevent a cycle (manual SQL, seed data, race outside the lock), recursion will still terminate.

### 12. OBSOLETE rejection at materialization, not at template authoring

A template can reference an `OBSOLETE` catalog part — authoring is not gated by lifecycle. The check fires at **materialization** (and at preview). The recursive walk visits every node, deduping `OBSOLETE` part numbers into a list; if the list is non-empty after the full traversal, the request is rejected with HTTP 409 and a payload listing every offender.

This matches the existing CRUD behavior that blocks new `BOMItem` creation referencing an `OBSOLETE` part. It enumerates the full set so the AUTHOR sees the entire blast radius in one shot rather than one error at a time.

### 13. Materialize via the existing `POST /bom-items` with an additive flag

Rather than introduce a separate `/materialize` endpoint, `POST /bom-items` gains a request-body field `explode_from_template: bool = false`. When `false`, the endpoint behaves as before. When `true`, the handler validates `bom_type=TECHNICAL`, the version is DRAFT (existing rule), the part is ACTIVE (existing rule), the part has at least one template row, and then calls the materialization service. On success it returns HTTP 201 with the root `BOMItem` and its full sub-tree nested in `children` (the `BOMItemReadWithChildren` schema).

### 14. Stoichiometric quantities in the indented tree; cascade only in `technical_flat`

`BOMItem.quantity` is recorded as **per unit of parent** (stoichiometric), exactly as written by the author. Materialization copies the per-edge `EngineeringTemplateItem.quantity` into each child's `BOMItem.quantity` verbatim. The engine does **not** multiply parent.qty × child.qty in the indented `BOMOutput.technical` output. This preserves the existing semantics, avoids invasive engine changes, and keeps the indented tree directly comparable to a hand-authored hierarchical BOM.

The cascade arithmetic — "to build one root, how many of *this leaf* do I need?" — lives only in `technical_flat` (decision 16).

### 15. Aggregation re-parents children of merged sibling representatives

`_aggregate_bom_items` groups siblings by `(part_number, parent_bom_item_id, bom_type)`, picks the lowest-`sequence` member as representative, and sums quantities across the group. The corrected algorithm additionally re-parents the children of every non-representative member under the representative (via `dataclasses.replace` on the cached `CachedBOMItem` snapshots; the cache is untouched), then recurses so identical children of merged parents collapse into one line with summed quantity. The walk is depth-first; emit order matches sequence ordering at every level so `_build_bom_output` attaches children in the intended order.

Without re-parenting, the children of a merged-out sibling kept their original `parent_bom_item_id`, lost their parent (now excluded from the included set), and surfaced as spurious roots in `technical`.

### 16. `technical_flat`: alphabetic, cascade-aggregated, present on every calculation

`BOMOutput` carries a `technical_flat: list[BOMFlatLineItem]` field, computed by the engine immediately after the indented tree is built. The algorithm is a recursive DFS that accumulates `{part_number: total_quantity}`, where each node's contribution is `ancestor_product × node.quantity`. Same `part_number` appearing in multiple branches sums across them. Output is alphabetically sorted by `part_number`; the field is empty when the technical tree is empty (root excluded).

`BOMFlatLineItem` carries `part_number`, `description`, `category`, `unit_of_measure`, and `total_quantity` — the same metadata as `BOMLineItem` minus pricing and hierarchy. `description`/`category`/`unit_of_measure` are sourced from the `catalog_map` already loaded for the indented tree; no extra DB roundtrip.

### 17. Snapshot immunity inherits from the existing mechanism

`Configuration.snapshot` stores the full `CalculationResponse`, which now includes `bom.technical_flat`. The flat list is therefore captured automatically at finalization and survives subsequent template, catalog, or price-list mutations. No additional snapshot logic is required.

### 18. Preview-explosion endpoint for dry-run validation

`GET /catalog-items/{part_number}/preview-explosion` (any authenticated user) performs the same recursive expansion as materialization without writing anything. It returns `{tree: [<root with descendants>], flat: [...], total_nodes: int, max_depth_reached: int}`, with `description`/`category`/`unit_of_measure` joined onto every entry of both `tree` and `flat`. Limit overflow returns HTTP 413; OBSOLETE presence returns HTTP 409 — same payload shapes as materialization. A part with no template returns a single root node, an empty flat, `total_nodes=1`, `max_depth_reached=0`.

### 19. Catalog item usage endpoint for impact assessment

`GET /catalog-items/{part_number}/usage` (ADMIN/AUTHOR) returns three lists:

- `templates_as_parent` — every `EngineeringTemplateItem` row where the part is the parent, ordered by `(sequence, child_part_number)`.
- `templates_as_child` — every row where it is a child, ordered by `(parent_part_number, sequence)`.
- `bom_items` — every `BOMItem` referencing the part, with `(bom_item_id, entity_version_id)` pairs ordered by `(entity_version_id, bom_item_id)`.

This complements the extended DELETE protection (decision 20) by giving AUTHORs a way to see the where-used graph before they act.

### 20. `DELETE /catalog-items/{id}` blocks on engineering template references

The existing DELETE protection counted `BOMItem` and `PriceListItem` references. It now also counts `EngineeringTemplateItem` rows where the part appears as parent or child. The 409 message format becomes:

```
"Catalog item '<part_number>' cannot be deleted: referenced by N BOM item(s), M price list item(s), and K engineering template item(s)"
```

The third counter completes the trio — every place that holds a live FK to `catalog_items.part_number` is now reflected in the error.

### 21. Asymmetric RBAC: template read open, usage restricted

`GET /catalog-items/{p}/template` and `GET /catalog-items/{p}/preview-explosion` are open to any authenticated user; the structure of a single product's composition is informational. `GET /catalog-items/{p}/usage` is restricted to ADMIN/AUTHOR because it reveals the cross-product where-used graph — product-engineering data, not configurator data.

### 22. Response payload shape for explosion errors

Both `POST /bom-items` (with `explode_from_template`) and `GET .../preview-explosion` use the same structured detail payloads:

- 413 (limit): `{"limit": "depth" | "nodes", "max": <configured>, "reached": <observed>}`
- 409 (OBSOLETE): `{"message": "...", "obsolete_parts": [<part_number>, ...]}`

This lets clients differentiate the two failure modes without parsing free-form messages.

### 23. Cycle-detection path payload format

Cycle 409 responses on template POST use `{"detail": {"message": "...", "cycle_path": [<parent>, <intermediate>, ..., <parent>]}}`. The path brackets `parent_part_number` at both ends so the closed cycle is explicit (e.g., `["A", "B", "C", "A"]`). Self-loops are reported as `[part, part]` (length-2 path representing the length-1 cycle).

### 24. Materialization runs without the advisory lock

The materialization transaction reads the template via PostgreSQL MVCC and gets a snapshot-consistent view of the graph at transaction start. Concurrent template edits commit visibility only after the materialization transaction completes. This avoids holding the graph lock during what may be a many-row insert; the trade-off is that a freshly committed template edit may not be visible to a materialization that started before it. For the authoring workflow this is acceptable — the next materialization sees the new edit.

### 25. Clone semantics: structural copy, not re-materialization

The existing `clone_version` logic copies `BOMItem` and `BOMItemRule` rows with ID remapping. Materialized rows are ordinary `BOMItem` rows and are cloned by the same code path. **No re-materialization happens on clone.** The destination version is a structural copy of the source at the moment of clone, even if the source's templates have since changed. This is consistent with the snap-detach decision (3).

### 26. Configuration upgrade re-evaluates the new version's BOM

Upgrading a DRAFT configuration to a newer `EntityVersion` re-points the configuration at the new version. The technical BOM at calculation time is the new version's BOM (which may include different materializations). The existing upgrade behavior is preserved; no new logic.

### 27. Logging at materialization time

Materialization emits one INFO-level structured log per call with `extra={parent_part_number, entity_version_id, total_nodes, max_depth_reached, duration_ms}` so the cost of an explosion is visible to operations.

### M1. Aggregation fix is a behavior change, not a feature

The corrected aggregation re-parenting (decision 15) is a semantic change to `BOMOutput.technical`: trees that previously surfaced orphan children at root now nest them under the surviving representative. No existing tests required updates because the prior coverage was narrow enough not to assert on the buggy shape, but the change is observable to clients that tolerated the old behavior.

### M2. New field on `BOMOutput` is additive

`technical_flat` is a new field on `BOMOutput`, defaulting to `[]`. Clients ignoring unknown fields see no change. Clients that asserted on the dict shape of `BOMOutput` get an extra key; the existing test suite did not require updates because assertions were field-targeted rather than full-dict.

## Consequences

- **Positive**: AUTHOR workflows no longer hand-replicate composite parts on every version. A `MOUSE-PRO` template lives once on the catalog and explodes on demand into every version that ships it.
- **Positive**: `technical_flat` answers the procurement question ("what materials does one configuration consume?") in O(tree size) at calculation time, frozen into FINALIZED snapshots automatically.
- **Positive**: The cycle detector + advisory lock turns the template graph into a guaranteed DAG at the application layer; the runtime depth/node limits are a defense-in-depth safety net.
- **Positive**: Snap-detach keeps `EntityVersion` the sole runtime source of truth for product structure. Subsequent template edits cannot mutate quotes that have already been issued.
- **Positive**: The aggregation re-parenting fix produces a correct nested tree for hand-authored *and* materialized BOMs that share the duplicate-sibling pattern.
- **Negative**: An AUTHOR who edits a template after materialization is responsible for re-materializing affected versions manually. There is no background reconciliation job (see "Known Limitations" below).
- **Negative**: Recursive explosion is implemented as level-by-level ORM queries (one query per parent visited). For deep templates this is N+1; an optimizer can fold it into a single recursive CTE later if profile data warrants.
- **Negative**: The `POST /bom-items` response shape now differs by case — `BOMItemReadWithChildren` always carries `children`, but it is `[]` when `explode_from_template=false`. Clients that strictly validate response shape may need to acknowledge the new field.

## Known Limitations and Future Work

1. **No re-explode endpoint.** Authors who want to refresh a materialization to reflect a template update must DELETE the parent `BOMItem` (cascade removes descendants) and POST it again with `explode_from_template=true`. A future `POST /bom-items/{id}/re-explode-from-template` with a `force=true` safety flag would streamline this; deferred because re-explosion drops manually added children of the target row, which is a workflow decision worth its own design pass.
2. **No template versioning.** The template graph is mutable in place; there is no historical record of what `MOUSE-PRO`'s template looked like six months ago. Materialized `BOMItem` rows on past `EntityVersion` rows serve as an implicit snapshot.
3. **No audit trail of materialization origin.** A materialized `BOMItem` is indistinguishable from a hand-written one. A soft tag (`created_from_template_at: datetime`) could be added later for diagnostics; out of scope for the current release.
4. **No background drift detection.** Snap-detach is deliberate, but means a template change is invisible to existing materializations. A CLI script or batch endpoint could surface "materializations that diverge from the current template" as a report.
5. **No `replaced_by` link on the catalog.** Inherited from `ADR_CATALOG_ITEM` decision: obsoleting a part does not point to a successor. The engineering BOM feature does not change this; future work could let templates reference the chain.

## Related

- [ADR: BOM Generation](ADR_BOM.md) — Underlying BOM model that materialized rows reuse; the corrected aggregation semantics live here.
- [ADR: Catalog Item](ADR_CATALOG_ITEM.md) — Templates attach to `CatalogItem`; the extended DELETE protection lives here.
- [ADR: Rule Expressions](ADR_RULE_EXPRESSIONS.md) — Why the engine does not introduce expression evaluation for cascade arithmetic; `technical_flat` is computed by a fixed traversal, not by user-authored expressions.
- [ADR: Inference Tree](ADR_INFERENCE_TREE.md) — Why the engine stays a waterfall rather than a graph; the template graph is an authoring artifact, not part of the runtime evaluation graph.
- [ADR: Re-hydration](ADR_REHYDRATION.md) — How `Configuration.snapshot` immunity propagates to `technical_flat` automatically.
