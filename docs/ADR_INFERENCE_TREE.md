# ADR: Waterfall Evaluation vs Inference Tree

## Status

**Accepted**

## Context

The rule engine needs a strategy to evaluate field states (visibility, availability, validation, etc.) when fields depend on each other. Two main approaches exist:

| Approach | How it works |
|----------|-------------|
| **Waterfall** (current) | Fields are evaluated in a fixed order (`step`, `sequence`). Each field can reference values of previously evaluated fields. Single pass, top-to-bottom. |
| **Inference tree** | A dependency graph (DAG) is built from rule conditions. Evaluation order is derived automatically via topological sort, with change propagation through the graph. |

## Decision

The rule engine uses **waterfall evaluation**. Inference tree / dependency graph evaluation is not implemented.

## Rationale

1. **Simplicity**: Waterfall is a single linear pass. No graph construction, no topological sort, no cycle detection. Easy to implement, debug, and reason about.

2. **Predictable for authors**: The rule author defines the evaluation order explicitly via `step` and `sequence`. There are no surprises — field B always evaluates after field A if it's ordered after it.

3. **Sufficient for CPQ**: Product configurators typically have a natural top-down flow (category → model → options → accessories). Fields rarely need to reference "downstream" values.

4. **No circular dependency risk**: Since fields can only reference previously evaluated values, circular references are impossible by design. An inference tree would need explicit cycle detection and error handling.

## Trade-offs

**What waterfall can't do:**
- A field cannot react to a field that comes *after* it in the sequence
- If dependencies change, the author must manually reorder fields
- Complex bidirectional dependencies (A affects B, B affects A) are not expressible

**Why that's acceptable:**
- CPQ configurators naturally flow top-down (broad choices first, details later)
- Reordering fields is a simple operation on the DRAFT version
- Bidirectional dependencies are rare in practice and often indicate a modeling problem

## Alternatives Considered

### Dependency graph with topological sort

Build a DAG from rule conditions, topologically sort fields, evaluate in dependency order.

**Rejected**: Adds significant complexity (graph construction, cycle detection, multi-pass evaluation) without a clear benefit for the target use case. Could be reconsidered if real-world usage reveals frequent need for non-linear dependencies.

### Hybrid approach

Keep waterfall as default, allow opt-in dependency tracking for specific fields.

**Rejected**: Two evaluation models in one engine increases cognitive load for authors and testing surface. Better to commit to one approach.

## References

- [Rule Engine Implementation](../app/services/rule_engine.py) — waterfall logic in `_process_field`
- [ADR: Rule Expressions](ADR_RULE_EXPRESSIONS.md) — related decision on single-field conditions
