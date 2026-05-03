import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    db_transaction,
    fetch_version_by_id,
    get_bom_item_or_404,
    get_editable_bom_item,
    require_admin_or_author,
    validate_catalog_reference,
    validate_version_is_draft,
)
from app.models.domain import BOMItem, BOMType, EngineeringTemplateItem, EntityVersion, Field, FieldType, User
from app.schemas.bom_item import BOMItemCreate, BOMItemRead, BOMItemReadWithChildren, BOMItemUpdate
from app.services.engineering_template import (
    ExplosionContainsObsoletePartsError,
    ExplosionLimitExceededError,
    materialize,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bom-items", tags=["BOM Items"])


def _validate_quantity(quantity: Decimal) -> None:
    """Validates quantity is positive."""
    if quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Quantity must be greater than 0.",
        )


def _validate_quantity_from_field(db: Session, field_id: int, version_id: int) -> None:
    """Validates quantity_from_field_id references a NUMBER field in the same version."""
    field = db.query(Field).filter(Field.id == field_id, Field.entity_version_id == version_id).first()
    if not field:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Field {field_id} not found in version {version_id}.",
        )
    if field.data_type != FieldType.NUMBER.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Field {field_id} must be of type NUMBER to use as quantity source. Got {field.data_type}.",
        )


def _validate_commercial_is_root(bom_type: str | BOMType, parent_bom_item_id: int | None) -> None:
    """Rejects COMMERCIAL items with a non-null parent (COMMERCIAL BOM is flat, root-level only)."""
    bom_type_val = bom_type.value if isinstance(bom_type, BOMType) else bom_type
    if bom_type_val == BOMType.COMMERCIAL.value and parent_bom_item_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="COMMERCIAL BOM items must be root-level (parent_bom_item_id must be null).",
        )


def _validate_parent_bom_item(db: Session, parent_id: int, version_id: int, exclude_id: int | None = None) -> None:
    """Validates parent_bom_item_id exists in the same version and doesn't create a cycle."""
    parent = db.query(BOMItem).filter(BOMItem.id == parent_id, BOMItem.entity_version_id == version_id).first()
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Parent BOM item {parent_id} not found in version {version_id}.",
        )

    # Circular reference check: walk up the parent chain
    if exclude_id is not None:
        current: BOMItem | None = parent
        while current is not None:
            if current.id == exclude_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Circular parent reference detected.",
                )
            current = (
                db.query(BOMItem).filter(BOMItem.id == current.parent_bom_item_id).first()
                if current.parent_bom_item_id
                else None
            )


@router.get("/", response_model=list[BOMItemRead])
def list_bom_items(
    entity_version_id: int,
    skip: int = Query(default=0, ge=0, description="Number of records to skip"),
    limit: int = Query(default=100, ge=0, le=100, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """List BOM items of a version, ordered by `sequence`. ADMIN/AUTHOR only."""

    items = (
        db.query(BOMItem)
        .filter(BOMItem.entity_version_id == entity_version_id)
        .order_by(BOMItem.sequence)
        .offset(skip)
        .limit(limit)
        .all()
    )

    logger.info(f"Returning {len(items)} BOM items for version {entity_version_id}")
    return items


@router.get("/{bom_item_id}", response_model=BOMItemRead)
def read_bom_item(
    bom_item: BOMItem = Depends(get_bom_item_or_404),
    current_user: User = Depends(require_admin_or_author),
):
    """Get a BOM item by id. ADMIN/AUTHOR only."""
    logger.debug(f"Reading BOM item {bom_item.id} by user {current_user.id}")
    return bom_item


@router.post("/", response_model=BOMItemReadWithChildren, status_code=status.HTTP_201_CREATED)
def create_bom_item(
    bom_data: BOMItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Create a BOM item on a DRAFT version. ADMIN/AUTHOR only.

    With `explode_from_template=true` (TECHNICAL only) the engineering
    template is materialized as a `BOMItem` sub-tree in one transaction;
    the response includes the descendants nested in `children`.
    """
    logger.info(
        f"Creating BOM item '{bom_data.part_number}' for version {bom_data.entity_version_id} "
        f"(explode_from_template={bom_data.explode_from_template}) by user {current_user.id}"
    )

    version = fetch_version_by_id(db, bom_data.entity_version_id)
    validate_version_is_draft(version)

    if bom_data.explode_from_template:
        return _create_bom_item_with_explosion(db, bom_data, version)

    return _create_bom_item_simple(db, bom_data, version)


def _create_bom_item_simple(db: Session, bom_data: BOMItemCreate, version: EntityVersion) -> BOMItem:
    validate_catalog_reference(db, bom_data.part_number, on_create=True)
    _validate_quantity(bom_data.quantity)

    if bom_data.quantity_from_field_id is not None:
        _validate_quantity_from_field(db, bom_data.quantity_from_field_id, bom_data.entity_version_id)

    _validate_commercial_is_root(bom_data.bom_type, bom_data.parent_bom_item_id)

    if bom_data.parent_bom_item_id is not None:
        _validate_parent_bom_item(db, bom_data.parent_bom_item_id, bom_data.entity_version_id)

    payload = bom_data.model_dump(exclude={"explode_from_template"})

    with db_transaction(db, f"create_bom_item '{bom_data.part_number}' for version {version.id}"):
        new_item = BOMItem(**payload)
        db.add(new_item)
        db.flush()

        logger.info(f"BOM item {new_item.id} created successfully: part_number='{bom_data.part_number}'")

    db.refresh(new_item)
    return new_item


def _create_bom_item_with_explosion(db: Session, bom_data: BOMItemCreate, version: EntityVersion) -> BOMItem:
    bom_type_value = bom_data.bom_type.value if isinstance(bom_data.bom_type, BOMType) else bom_data.bom_type
    if bom_type_value != BOMType.TECHNICAL.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="explode_from_template requires bom_type=TECHNICAL.",
        )

    validate_catalog_reference(db, bom_data.part_number, on_create=True)
    _validate_quantity(bom_data.quantity)

    if bom_data.quantity_from_field_id is not None:
        _validate_quantity_from_field(db, bom_data.quantity_from_field_id, bom_data.entity_version_id)

    if bom_data.parent_bom_item_id is not None:
        _validate_parent_bom_item(db, bom_data.parent_bom_item_id, bom_data.entity_version_id)

    template_exists = (
        db.query(EngineeringTemplateItem.id)
        .filter(EngineeringTemplateItem.parent_part_number == bom_data.part_number)
        .first()
    )
    if template_exists is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Catalog item '{bom_data.part_number}' has no engineering template; "
                "explode_from_template requires one."
            ),
        )

    try:
        root = materialize(
            db,
            entity_version_id=bom_data.entity_version_id,
            root_part_number=bom_data.part_number,
            parent_bom_item_id=bom_data.parent_bom_item_id,
            root_quantity=bom_data.quantity,
            root_quantity_from_field_id=bom_data.quantity_from_field_id,
            root_sequence=bom_data.sequence,
            root_suppress_auto_explode=False,
        )
        db.commit()
    except ExplosionLimitExceededError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "limit": exc.limit_name,
                "max": exc.max_value,
                "reached": exc.reached,
            },
        ) from None
    except ExplosionContainsObsoletePartsError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Engineering BOM explosion encountered OBSOLETE parts.",
                "obsolete_parts": exc.obsolete_parts,
            },
        ) from None
    except SQLAlchemyError as exc:
        db.rollback()
        logger.error(
            f"Database error during materialization of '{bom_data.part_number}': {exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {exc}",
        ) from None

    db.refresh(root)
    logger.info(f"BOM item {root.id} materialized successfully: part_number='{bom_data.part_number}'")
    return root


@router.patch("/{bom_item_id}", response_model=BOMItemRead)
def update_bom_item(
    bom_update: BOMItemUpdate,
    bom_item: BOMItem = Depends(get_editable_bom_item),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Update a BOM item on a DRAFT version. ADMIN/AUTHOR only."""

    update_data = bom_update.model_dump(exclude_unset=True)

    if not update_data:
        return bom_item

    effective_type = update_data.get("bom_type", bom_item.bom_type)

    if "part_number" in update_data and update_data["part_number"] != bom_item.part_number:
        validate_catalog_reference(db, update_data["part_number"], on_create=False)

    if "quantity" in update_data:
        _validate_quantity(update_data["quantity"])

    if "quantity_from_field_id" in update_data and update_data["quantity_from_field_id"] is not None:
        _validate_quantity_from_field(db, update_data["quantity_from_field_id"], bom_item.entity_version_id)

    if "bom_type" in update_data or "parent_bom_item_id" in update_data:
        effective_parent = update_data.get("parent_bom_item_id", bom_item.parent_bom_item_id)
        _validate_commercial_is_root(effective_type, effective_parent)

    if "parent_bom_item_id" in update_data and update_data["parent_bom_item_id"] is not None:
        _validate_parent_bom_item(
            db, update_data["parent_bom_item_id"], bom_item.entity_version_id, exclude_id=bom_item.id
        )

    with db_transaction(db, f"update_bom_item {bom_item.id}"):
        for key, value in update_data.items():
            setattr(bom_item, key, value)

        logger.info(f"BOM item {bom_item.id} updated successfully")

    db.refresh(bom_item)
    return bom_item


@router.delete("/{bom_item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bom_item(
    bom_item: BOMItem = Depends(get_editable_bom_item),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_author),
):
    """Delete a BOM item (cascades to children) on a DRAFT version. ADMIN/AUTHOR only."""

    with db_transaction(db, f"delete_bom_item {bom_item.id}"):
        part_number = bom_item.part_number
        db.delete(bom_item)

        logger.info(f"BOM item {bom_item.id} ('{part_number}') deleted successfully")

    return None
