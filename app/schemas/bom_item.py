from decimal import Decimal

from pydantic import Field

from app.models.domain import BOMType

from .base_schema import BaseSchema


class BOMItemBase(BaseSchema):
    """Base properties shared by create and read operations."""

    bom_type: BOMType
    part_number: str = Field(..., max_length=100)
    quantity: Decimal = Decimal("1")
    quantity_from_field_id: int | None = None
    sequence: int = 0


class BOMItemCreate(BOMItemBase):
    """Schema for creating a BOM item (POST).

    `explode_from_template=true` instructs the server to materialize the
    engineering template of `part_number` into a hierarchy of BOMItems with
    this row as the root. Requires `bom_type=TECHNICAL` and a non-empty
    template on the part. The response is the root with its full sub-tree.
    """

    entity_version_id: int
    parent_bom_item_id: int | None = None
    explode_from_template: bool = False


class BOMItemUpdate(BaseSchema):
    """Schema for partially updating a BOM item (PATCH)."""

    parent_bom_item_id: int | None = None
    bom_type: BOMType | None = None
    part_number: str | None = Field(None, max_length=100)
    quantity: Decimal | None = None
    quantity_from_field_id: int | None = None
    sequence: int | None = None
    suppress_auto_explode: bool | None = None


class BOMItemRead(BOMItemBase):
    """Schema for reading BOM item data (GET responses)."""

    id: int
    entity_version_id: int
    parent_bom_item_id: int | None = None
    suppress_auto_explode: bool = False


class BOMItemReadWithChildren(BOMItemRead):
    """Read schema that nests the recursive `children` sub-tree.

    Returned by `POST /bom-items` when `explode_from_template=true` so the
    caller receives the entire materialized hierarchy in one response.
    """

    children: list["BOMItemReadWithChildren"] = Field(default_factory=list)
