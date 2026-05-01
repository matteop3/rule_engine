import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import db_transaction, get_current_user, require_admin_or_author
from app.models.domain import CatalogItem, EngineeringTemplateItem, User
from app.schemas.engineering_template_item import (
    EngineeringTemplateItemCreate,
    EngineeringTemplateItemRead,
    EngineeringTemplateItemUpdate,
    PreviewExplosionResponse,
    PreviewFlatItem,
    PreviewTreeNode,
)
from app.services.engineering_template import (
    ExplodedNode,
    ExplosionContainsObsoletePartsError,
    ExplosionLimitExceededError,
    acquire_template_graph_lock,
    explode,
    flatten,
    would_create_cycle,
)

# ============================================================
# LOGGING SETUP
# ============================================================

logger = logging.getLogger(__name__)

# ============================================================
# ROUTER SETUP
# ============================================================

router = APIRouter(prefix="/catalog-items", tags=["Engineering Template"])

# ============================================================
# HELPERS
# ============================================================


def _get_parent_catalog_or_404(part_number: str, db: Session) -> CatalogItem:
    """Resolve the catalog item that owns the template, or raise 404."""
    parent = db.query(CatalogItem).filter(CatalogItem.part_number == part_number).first()
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Catalog item '{part_number}' not found.",
        )
    return parent


def _get_template_item_or_404(db: Session, parent_part_number: str, item_id: int) -> EngineeringTemplateItem:
    """Resolve a template item scoped to the URL's parent, or raise 404."""
    item = (
        db.query(EngineeringTemplateItem)
        .filter(
            EngineeringTemplateItem.id == item_id,
            EngineeringTemplateItem.parent_part_number == parent_part_number,
        )
        .first()
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"Engineering template item {item_id} not found in template of '{parent_part_number}'."),
        )
    return item


def _ensure_child_catalog_exists(db: Session, child_part_number: str) -> None:
    """Reject template edges that point to a catalog row that does not exist."""
    exists = db.query(CatalogItem.id).filter(CatalogItem.part_number == child_part_number).first()
    if exists is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Catalog item '{child_part_number}' does not exist.",
        )


# ============================================================
# ENDPOINTS
# ============================================================


@router.get("/{part_number}/template", response_model=list[EngineeringTemplateItemRead])
def list_template_items(
    part_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return every direct-child template row attached to a catalog item.

    Results are ordered by `(sequence, child_part_number)` so siblings appear
    in the order the author intended, with alphabetic tie-breaking. An empty
    list is returned when the part has no template.

    Access Control:
        - Any authenticated user can read template items.
    """
    logger.debug(f"Listing template items for '{part_number}' by user {current_user.id}")

    _get_parent_catalog_or_404(part_number, db)

    items = (
        db.query(EngineeringTemplateItem)
        .filter(EngineeringTemplateItem.parent_part_number == part_number)
        .order_by(EngineeringTemplateItem.sequence, EngineeringTemplateItem.child_part_number)
        .all()
    )

    logger.info(f"Returning {len(items)} template items for '{part_number}'")
    return items


@router.post(
    "/{part_number}/template/items",
    response_model=EngineeringTemplateItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_template_item(
    part_number: str,
    payload: EngineeringTemplateItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """
    Attach a child to the engineering template of a catalog item.

    Validation:
        - Parent catalog item must exist (HTTP 404).
        - Child catalog item must exist (HTTP 409).
        - Edge must not close a cycle in the template graph (HTTP 409).
        - Pair `(parent_part_number, child_part_number)` must be unique (HTTP 409).

    Concurrency:
        Acquires the engineering-template-graph advisory lock so that two
        concurrent edge insertions cannot together construct a cycle that
        each would have considered safe in isolation.

    Access Control:
        - Only ADMIN and AUTHOR can attach template items.
    """
    logger.info(
        f"Creating template item for parent '{part_number}' "
        f"with child '{payload.child_part_number}' by user {current_user.id}"
    )

    _get_parent_catalog_or_404(part_number, db)

    with db_transaction(db, f"create_template_item parent='{part_number}'"):
        acquire_template_graph_lock(db)

        _ensure_child_catalog_exists(db, payload.child_part_number)

        cycles, cycle_path = would_create_cycle(db, part_number, payload.child_part_number)
        if cycles:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        f"Adding child '{payload.child_part_number}' to '{part_number}' "
                        "would create a cycle in the engineering template graph."
                    ),
                    "cycle_path": cycle_path,
                },
            )

        existing = (
            db.query(EngineeringTemplateItem.id)
            .filter(
                EngineeringTemplateItem.parent_part_number == part_number,
                EngineeringTemplateItem.child_part_number == payload.child_part_number,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Template of '{part_number}' already contains '{payload.child_part_number}'."),
            )

        new_item = EngineeringTemplateItem(
            parent_part_number=part_number,
            child_part_number=payload.child_part_number,
            quantity=payload.quantity,
            sequence=payload.sequence,
            suppress_child_explosion=payload.suppress_child_explosion,
            created_by_id=current_user.id,
            updated_by_id=current_user.id,
        )
        db.add(new_item)
        db.flush()

        logger.info(f"Template item {new_item.id} created: '{part_number}' -> '{payload.child_part_number}'")

    db.refresh(new_item)
    return new_item


@router.patch(
    "/{part_number}/template/items/{item_id}",
    response_model=EngineeringTemplateItemRead,
)
def update_template_item(
    part_number: str,
    item_id: int,
    payload: EngineeringTemplateItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """
    Update the mutable fields of a template item.

    Mutable: `quantity`, `sequence`, `suppress_child_explosion`. Any payload
    that includes `parent_part_number` or `child_part_number` is rejected
    with HTTP 422 at the schema layer.

    Concurrency:
        Acquires the engineering-template-graph advisory lock for symmetry
        with POST/DELETE even though the mutable fields cannot change graph
        topology.

    Access Control:
        - Only ADMIN and AUTHOR can update template items.
    """
    logger.info(f"Updating template item {item_id} of '{part_number}' by user {current_user.id}")

    _get_parent_catalog_or_404(part_number, db)
    item = _get_template_item_or_404(db, part_number, item_id)

    update_data = payload.model_dump(exclude_unset=True)

    if not update_data:
        logger.warning(f"Empty update request for template item {item_id}")
        return item

    with db_transaction(db, f"update_template_item {item_id}"):
        acquire_template_graph_lock(db)

        for key, value in update_data.items():
            setattr(item, key, value)
        item.updated_by_id = current_user.id

        logger.info(f"Template item {item_id} updated successfully")

    db.refresh(item)
    return item


def _collect_part_numbers(node: ExplodedNode, accumulator: set[str]) -> None:
    accumulator.add(node.part_number)
    for child in node.children:
        _collect_part_numbers(child, accumulator)


def _build_preview_tree(node: ExplodedNode, catalog_map: dict[str, CatalogItem]) -> PreviewTreeNode:
    catalog = catalog_map.get(node.part_number)
    return PreviewTreeNode(
        part_number=node.part_number,
        quantity=node.quantity,
        sequence=node.sequence,
        suppress_auto_explode=node.suppress_auto_explode,
        description=catalog.description if catalog is not None else None,
        category=catalog.category if catalog is not None else None,
        unit_of_measure=catalog.unit_of_measure if catalog is not None else None,
        children=[_build_preview_tree(c, catalog_map) for c in node.children],
    )


@router.get(
    "/{part_number}/preview-explosion",
    response_model=PreviewExplosionResponse,
)
def preview_explosion(
    part_number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Dry-run materialization of a catalog part's engineering template.

    Returns the indented expansion (`tree`, a single root inside a list),
    the cascade-aggregated descendant material list (`flat`, alphabetic by
    `part_number`), and the metrics `total_nodes` / `max_depth_reached`.
    Catalog metadata (`description`, `category`, `unit_of_measure`) is
    joined onto every entry of both `tree` and `flat`.

    A part with no template returns a single root node, an empty `flat`,
    `total_nodes=1`, `max_depth_reached=0`. Limit overflow returns HTTP 413
    and OBSOLETE-part presence returns HTTP 409, mirroring the
    materialization endpoint.

    Access Control:
        - Any authenticated user can preview.
    """
    logger.debug(f"Previewing explosion for '{part_number}' by user {current_user.id}")

    if db.query(CatalogItem.id).filter(CatalogItem.part_number == part_number).first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Catalog item '{part_number}' not found.",
        )

    try:
        result = explode(db, part_number)
    except ExplosionLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "limit": exc.limit_name,
                "max": exc.max_value,
                "reached": exc.reached,
            },
        ) from None
    except ExplosionContainsObsoletePartsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Engineering BOM explosion encountered OBSOLETE parts.",
                "obsolete_parts": exc.obsolete_parts,
            },
        ) from None

    referenced_parts: set[str] = set()
    _collect_part_numbers(result.tree, referenced_parts)

    catalog_rows = db.query(CatalogItem).filter(CatalogItem.part_number.in_(referenced_parts)).all()
    catalog_map: dict[str, CatalogItem] = {row.part_number: row for row in catalog_rows}

    tree_node = _build_preview_tree(result.tree, catalog_map)
    flat_items = [
        PreviewFlatItem(
            part_number=pn,
            total_quantity=total,
            description=catalog_map[pn].description if pn in catalog_map else None,
            category=catalog_map[pn].category if pn in catalog_map else None,
            unit_of_measure=catalog_map[pn].unit_of_measure if pn in catalog_map else None,
        )
        for pn, total in flatten(result.tree)
    ]

    logger.info(
        f"Preview explosion of '{part_number}': "
        f"total_nodes={result.total_nodes} "
        f"max_depth_reached={result.max_depth_reached} "
        f"flat_rows={len(flat_items)}"
    )

    return PreviewExplosionResponse(
        tree=[tree_node],
        flat=flat_items,
        total_nodes=result.total_nodes,
        max_depth_reached=result.max_depth_reached,
    )


@router.delete(
    "/{part_number}/template/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_template_item(
    part_number: str,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """
    Remove a single child from the engineering template of a catalog item.

    Concurrency:
        Acquires the engineering-template-graph advisory lock for symmetry
        with POST/PATCH.

    Access Control:
        - Only ADMIN and AUTHOR can remove template items.
    """
    logger.info(f"Deleting template item {item_id} of '{part_number}' by user {current_user.id}")

    _get_parent_catalog_or_404(part_number, db)
    item = _get_template_item_or_404(db, part_number, item_id)

    with db_transaction(db, f"delete_template_item {item_id}"):
        acquire_template_graph_lock(db)
        db.delete(item)

        logger.info(f"Template item {item_id} deleted successfully")

    return None
