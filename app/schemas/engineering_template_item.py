from decimal import Decimal

from pydantic import Field, model_validator

from .base_schema import AuditSchemaMixin, BaseSchema


class PreviewTreeNode(BaseSchema):
    """A single node of the preview-explosion tree, with catalog metadata."""

    part_number: str
    quantity: Decimal
    sequence: int
    suppress_auto_explode: bool
    description: str | None = None
    category: str | None = None
    unit_of_measure: str | None = None
    children: list["PreviewTreeNode"] = Field(default_factory=list)


class PreviewFlatItem(BaseSchema):
    """A single row of the preview-explosion flat list, cascade-aggregated."""

    part_number: str
    total_quantity: Decimal
    description: str | None = None
    category: str | None = None
    unit_of_measure: str | None = None


class PreviewExplosionResponse(BaseSchema):
    """
    Dry-run materialization of a catalog part's engineering template.

    `tree` is the indented expansion (a single root inside a list).
    `flat` is the cascade-aggregated material list, alphabetically sorted by
    `part_number`. `total_nodes` and `max_depth_reached` mirror the metrics
    a real materialization would report.
    """

    tree: list[PreviewTreeNode]
    flat: list[PreviewFlatItem]
    total_nodes: int
    max_depth_reached: int


class EngineeringTemplateItemBase(BaseSchema):
    """Base properties shared by create and read operations."""

    child_part_number: str = Field(..., min_length=1, max_length=100)
    quantity: Decimal = Field(..., gt=0)
    sequence: int = Field(0, ge=0)
    suppress_child_explosion: bool = False


class EngineeringTemplateItemCreate(EngineeringTemplateItemBase):
    """Schema for creating a template item (POST)."""


class EngineeringTemplateItemRead(EngineeringTemplateItemBase, AuditSchemaMixin):
    """Schema for reading template item data (GET responses)."""

    id: int
    parent_part_number: str


class EngineeringTemplateItemUpdate(BaseSchema):
    """Schema for partially updating a template item (PATCH).

    Only `quantity`, `sequence`, and `suppress_child_explosion` are mutable.
    The graph endpoints (`parent_part_number`, `child_part_number`) are
    immutable: changing them would require re-validating the DAG, which is
    indistinguishable from deleting the row and creating a new one.
    """

    quantity: Decimal | None = Field(None, gt=0)
    sequence: int | None = Field(None, ge=0)
    suppress_child_explosion: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_immutable_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            for forbidden in ("parent_part_number", "child_part_number"):
                if forbidden in data:
                    raise ValueError(
                        f"{forbidden} cannot be modified; delete this template item and create a new one instead"
                    )
        return data
