from pydantic import Field, model_validator

from app.models.domain import CatalogItemStatus

from .base_schema import AuditSchemaMixin, BaseSchema
from .engineering_template_item import EngineeringTemplateItemRead


class CatalogItemBase(BaseSchema):
    """Base properties shared by create and read operations."""

    part_number: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    unit_of_measure: str = Field("PC", min_length=1, max_length=20)
    category: str | None = Field(None, max_length=100)
    status: CatalogItemStatus = CatalogItemStatus.ACTIVE
    notes: str | None = None


class CatalogItemCreate(CatalogItemBase):
    """Schema for creating a catalog item (POST)."""


class CatalogItemRead(CatalogItemBase, AuditSchemaMixin):
    """Schema for reading catalog item data (GET responses)."""

    id: int


class CatalogItemUpdate(BaseSchema):
    """Schema for partially updating a catalog item (PATCH).

    The `part_number` field is the immutable business key and cannot be
    modified; to retire a part, set `status` to OBSOLETE and create a new
    entry with the desired number.
    """

    description: str | None = Field(None, min_length=1)
    unit_of_measure: str | None = Field(None, min_length=1, max_length=20)
    category: str | None = Field(None, max_length=100)
    status: CatalogItemStatus | None = None
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_part_number(cls, data: object) -> object:
        if isinstance(data, dict) and "part_number" in data:
            raise ValueError("part_number cannot be modified; obsolete the entry and create a new one instead")
        return data


class CatalogItemBOMReference(BaseSchema):
    """A single `BOMItem` reference to a catalog item."""

    bom_item_id: int
    entity_version_id: int


class CatalogItemUsageResponse(BaseSchema):
    """
    Where-used view of a catalog item.

    Returned by `GET /catalog-items/{part_number}/usage`. Lets authors assess
    the impact of a catalog mutation (status change, deletion) before acting.
    """

    part_number: str
    templates_as_parent: list[EngineeringTemplateItemRead]
    templates_as_child: list[EngineeringTemplateItemRead]
    bom_items: list[CatalogItemBOMReference]
