"""Graph operations on `EngineeringTemplateItem`: cycle detection, advisory lock, recursive
explosion, and BOM materialization. Caller owns the transaction.
"""

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import (
    BOMItem,
    BOMType,
    CatalogItem,
    CatalogItemStatus,
    EngineeringTemplateItem,
)

logger = logging.getLogger(__name__)

_GRAPH_LOCK_KEY = "engineering_template_graph"


@dataclass
class ExplodedNode:
    """A single node of an exploded template tree.

    The root carries the placeholder values `quantity=1`, `sequence=0`,
    `suppress_auto_explode=False`. Callers that need the root with
    application-specific values (e.g., `materialize` with the caller-provided
    root quantity) override them after the fact.
    """

    part_number: str
    quantity: Decimal
    sequence: int
    suppress_auto_explode: bool
    children: list["ExplodedNode"] = field(default_factory=list)


@dataclass
class ExplosionResult:
    """The full outcome of an `explode` call."""

    tree: ExplodedNode
    total_nodes: int
    max_depth_reached: int


class ExplosionLimitExceededError(Exception):
    """Raised when an explosion exceeds `MAX_BOM_EXPLOSION_DEPTH` or `..._NODES`."""

    def __init__(self, limit_name: str, max_value: int, reached: int):
        self.limit_name = limit_name
        self.max_value = max_value
        self.reached = reached
        super().__init__(f"Engineering BOM explosion exceeded {limit_name} limit: max={max_value}, reached={reached}")


class ExplosionContainsObsoletePartsError(Exception):
    """Raised when any node of the explosion references an OBSOLETE catalog part."""

    def __init__(self, obsolete_parts: list[str]):
        self.obsolete_parts = obsolete_parts
        super().__init__(f"Engineering BOM explosion encountered OBSOLETE parts: {obsolete_parts}")


def acquire_template_graph_lock(db: Session) -> None:
    """Take a transactional advisory lock that serializes template-graph mutations cluster-wide.

    Required for every POST/PATCH/DELETE on `engineering_template_items` to
    prevent two concurrent edge inserts from jointly closing a cycle. Released
    automatically on commit or rollback. Reads do not need it.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": _GRAPH_LOCK_KEY})


def would_create_cycle(
    db: Session,
    parent_part_number: str,
    child_part_number: str,
) -> tuple[bool, list[str]]:
    """Detect whether adding `(parent, child)` would close a cycle in the template graph.

    Returns `(True, path)` with `path = [parent, ..., parent]` if a cycle would
    form (self-loops report `[part, part]`); `(False, [])` otherwise.
    """
    if parent_part_number == child_part_number:
        return True, [parent_part_number, parent_part_number]

    visited: set[str] = set()
    stack: list[tuple[str, list[str]]] = [(child_part_number, [parent_part_number, child_part_number])]

    while stack:
        current, path = stack.pop()
        if current in visited:
            continue
        visited.add(current)

        descendants = (
            db.query(EngineeringTemplateItem.child_part_number)
            .filter(EngineeringTemplateItem.parent_part_number == current)
            .all()
        )

        for (descendant,) in descendants:
            if descendant == parent_part_number:
                return True, [*path, descendant]
            if descendant not in visited:
                stack.append((descendant, [*path, descendant]))

    return False, []


def explode(db: Session, root_part_number: str) -> ExplosionResult:
    """Recursively expand a catalog part's template, bounded by depth and node-count limits.

    Edges with `suppress_child_explosion=True` become leaves with
    `suppress_auto_explode=True`. OBSOLETE parts encountered during the walk
    are collected and reported via `ExplosionContainsObsoletePartsError` at the end.
    Depth/node-count breaches raise `ExplosionLimitExceededError` immediately.
    """
    state = {"total_nodes": 0, "max_depth_reached": 0}
    obsolete_parts: list[str] = []
    obsolete_seen: set[str] = set()
    catalog_status_cache: dict[str, CatalogItemStatus | None] = {}

    def _status_of(part_number: str) -> CatalogItemStatus | None:
        if part_number in catalog_status_cache:
            return catalog_status_cache[part_number]
        item = db.query(CatalogItem).filter(CatalogItem.part_number == part_number).first()
        status = item.status if item is not None else None
        catalog_status_cache[part_number] = status
        return status

    def _recurse(
        part_number: str,
        quantity: Decimal,
        sequence: int,
        suppress_auto_explode: bool,
        depth: int,
    ) -> ExplodedNode:
        state["total_nodes"] += 1
        if state["total_nodes"] > settings.MAX_BOM_EXPLOSION_NODES:
            raise ExplosionLimitExceededError("nodes", settings.MAX_BOM_EXPLOSION_NODES, state["total_nodes"])
        if depth > state["max_depth_reached"]:
            state["max_depth_reached"] = depth
        if depth > settings.MAX_BOM_EXPLOSION_DEPTH:
            raise ExplosionLimitExceededError("depth", settings.MAX_BOM_EXPLOSION_DEPTH, depth)

        if _status_of(part_number) == CatalogItemStatus.OBSOLETE and part_number not in obsolete_seen:
            obsolete_seen.add(part_number)
            obsolete_parts.append(part_number)

        node = ExplodedNode(
            part_number=part_number,
            quantity=quantity,
            sequence=sequence,
            suppress_auto_explode=suppress_auto_explode,
            children=[],
        )

        if not suppress_auto_explode:
            children = (
                db.query(EngineeringTemplateItem)
                .filter(EngineeringTemplateItem.parent_part_number == part_number)
                .order_by(
                    EngineeringTemplateItem.sequence,
                    EngineeringTemplateItem.child_part_number,
                )
                .all()
            )
            for edge in children:
                child_node = _recurse(
                    edge.child_part_number,
                    edge.quantity,
                    edge.sequence,
                    edge.suppress_child_explosion,
                    depth + 1,
                )
                node.children.append(child_node)

        return node

    root = _recurse(root_part_number, Decimal("1"), 0, False, 0)

    if obsolete_parts:
        raise ExplosionContainsObsoletePartsError(obsolete_parts)

    return ExplosionResult(
        tree=root,
        total_nodes=state["total_nodes"],
        max_depth_reached=state["max_depth_reached"],
    )


def flatten(tree: ExplodedNode, root_quantity: Decimal = Decimal("1")) -> list[tuple[str, Decimal]]:
    """Cascade-multiply quantities through an exploded tree and aggregate by `part_number`.

    Root is excluded; each descendant contributes `root_quantity × ∏(ancestor_qty) × node.quantity`.
    Returns `(part_number, total_quantity)` pairs sorted by `part_number`.
    """
    totals: dict[str, Decimal] = {}

    def _walk(node: ExplodedNode, ancestor_product: Decimal) -> None:
        for child in node.children:
            child_total = ancestor_product * child.quantity
            totals[child.part_number] = totals.get(child.part_number, Decimal("0")) + child_total
            _walk(child, child_total)

    _walk(tree, root_quantity)

    return sorted(totals.items())


def materialize(
    db: Session,
    *,
    entity_version_id: int,
    root_part_number: str,
    parent_bom_item_id: int | None,
    root_quantity: Decimal,
    root_quantity_from_field_id: int | None,
    root_sequence: int,
    root_suppress_auto_explode: bool,
) -> BOMItem:
    """Persist a recursively exploded template as TECHNICAL `BOMItem` rows on a DRAFT version.

    Root attributes come from the caller; descendants copy per-edge template
    values. `EngineeringTemplateItem.suppress_child_explosion` propagates to
    `BOMItem.suppress_auto_explode`. Quantities stay stoichiometric (per unit
    of parent); the cascade view lives in `technical_flat` generation.

    Raises `ExplosionLimitExceededError` on depth/node breach,
    `ExplosionContainsObsoletePartsError` on any OBSOLETE part.
    """
    start = time.perf_counter()

    result = explode(db, root_part_number)

    def _insert(node: ExplodedNode, parent_db_id: int | None, *, is_root: bool) -> BOMItem:
        if is_root:
            quantity = root_quantity
            quantity_field = root_quantity_from_field_id
            sequence = root_sequence
            suppress = root_suppress_auto_explode
        else:
            quantity = node.quantity
            quantity_field = None
            sequence = node.sequence
            suppress = node.suppress_auto_explode

        bom_item = BOMItem(
            entity_version_id=entity_version_id,
            parent_bom_item_id=parent_db_id,
            bom_type=BOMType.TECHNICAL.value,
            part_number=node.part_number,
            quantity=quantity,
            quantity_from_field_id=quantity_field,
            sequence=sequence,
            suppress_auto_explode=suppress,
        )
        db.add(bom_item)
        db.flush()

        for child in node.children:
            _insert(child, bom_item.id, is_root=False)

        return bom_item

    root_bom = _insert(result.tree, parent_bom_item_id, is_root=True)

    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "BOM materialized from engineering template",
        extra={
            "parent_part_number": root_part_number,
            "entity_version_id": entity_version_id,
            "total_nodes": result.total_nodes,
            "max_depth_reached": result.max_depth_reached,
            "duration_ms": duration_ms,
        },
    )

    return root_bom
