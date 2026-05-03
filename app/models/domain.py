"""SQLAlchemy ORM models and enums for the rule engine domain."""

import datetime as dt
import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# ============================================================
# ENUMS
# ============================================================


class VersionStatus(str, enum.Enum):
    """Lifecycle status for `EntityVersion`.

    - DRAFT: editable by ADMIN/AUTHOR.
    - PUBLISHED: active, read-only, used by the rule engine.
    - ARCHIVED: historical, read-only.
    """

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class UserRole(str, enum.Enum):
    """Role-based access control levels.

    - ADMIN: full system access including user management.
    - AUTHOR: manages entities, versions, rules.
    - USER: uses the configurator and owns configurations.
    """

    ADMIN = "admin"
    AUTHOR = "author"
    USER = "user"


class ConfigurationStatus(str, enum.Enum):
    """Mutability state of a `Configuration`.

    - DRAFT: mutable sandbox; inputs, version, and record are editable.
    - FINALIZED: immutable snapshot; no edits allowed.
    """

    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class FieldType(str, enum.Enum):
    """Data type expected for a `Field` value."""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"


class RuleType(str, enum.Enum):
    """Business-logic rule category.

    - VISIBILITY: shows/hides the target field.
    - AVAILABILITY: filters available options on a multi-choice field.
    - CALCULATION: sets the field value and marks it readonly.
    - EDITABILITY: toggles readonly state.
    - MANDATORY: toggles required state.
    - VALIDATION: rejects invalid combinations with an error message.
    """

    VISIBILITY = "visibility"
    AVAILABILITY = "availability"
    CALCULATION = "calculation"
    EDITABILITY = "editability"
    MANDATORY = "mandatory"
    VALIDATION = "validation"


class CatalogItemStatus(str, enum.Enum):
    """Lifecycle status for `CatalogItem`.

    - ACTIVE: can be referenced by new rows.
    - OBSOLETE: existing references keep working; new references are blocked.
    """

    ACTIVE = "ACTIVE"
    OBSOLETE = "OBSOLETE"


class BOMType(str, enum.Enum):
    """BOM item classification.

    - TECHNICAL: assembly structure, supports hierarchy.
    - COMMERCIAL: priced line item, flat (root-level only).
    """

    TECHNICAL = "TECHNICAL"
    COMMERCIAL = "COMMERCIAL"


# ============================================================
# MIXINS
# ============================================================


class AuditMixin:
    """Adds `created_at`/`updated_at` timestamps and `created_by_id`/`updated_by_id` user FKs."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, comment="Timestamp when record was created"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True, comment="Timestamp when record was last updated"
    )
    created_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, comment="ID of user who created this record"
    )
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, comment="ID of user who last updated this record"
    )


# ============================================================
# DOMAIN MODELS
# ============================================================


class Entity(Base, AuditMixin):
    """Logical container for versioned configurations (e.g., a configurable product)."""

    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    versions: Mapped[list["EntityVersion"]] = relationship(back_populates="entity", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Entity id={self.id} name='{self.name}'>"

    def __str__(self) -> str:
        return self.name


class EntityVersion(Base, AuditMixin):
    """Versioned snapshot of an `Entity`.

    Lifecycle: DRAFT → PUBLISHED → ARCHIVED. At most one PUBLISHED per Entity.
    """

    __tablename__ = "entity_versions"
    __table_args__ = (Index("ix_entity_status", "entity_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))

    version_number: Mapped[int] = mapped_column(Integer, comment="Sequential version number")
    status: Mapped[VersionStatus] = mapped_column(String(20), default=VersionStatus.DRAFT)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # SKU generation fields
    sku_base: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="Base SKU code for this product version (e.g., 'LPT-PRO')"
    )
    sku_delimiter: Mapped[str] = mapped_column(
        String(5), default="-", nullable=False, comment="Delimiter for SKU segments (default: '-')"
    )

    # Relationships
    entity: Mapped["Entity"] = relationship(back_populates="versions")
    fields: Mapped[list["Field"]] = relationship(back_populates="entity_version", cascade="all, delete-orphan")
    rules: Mapped[list["Rule"]] = relationship(back_populates="entity_version", cascade="all, delete-orphan")
    bom_items: Mapped[list["BOMItem"]] = relationship(back_populates="entity_version", cascade="all, delete-orphan")
    configurations: Mapped[list["Configuration"]] = relationship(
        back_populates="entity_version", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<EntityVersion id={self.id} entity_id={self.entity_id} v{self.version_number} status={self.status}>"

    def __str__(self) -> str:
        return f"v{self.version_number} ({self.status})"


class Field(Base):
    """Configurable property of an `Entity`.

    Free-value (`is_free_value=True`) accepts arbitrary text; option-based
    fields select from predefined `Value` rows.
    """

    __tablename__ = "fields"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entity_version_id: Mapped[int] = mapped_column(ForeignKey("entity_versions.id"))

    name: Mapped[str] = mapped_column(String(100), comment="Internal field name")
    label: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Display label for UI")
    data_type: Mapped[FieldType] = mapped_column(String(50), default=FieldType.STRING)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_readonly: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    is_free_value: Mapped[bool] = mapped_column(Boolean, default=False, comment="If True, user can enter any value")
    default_value: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Default value for free-value fields only"
    )
    sku_modifier_when_filled: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment=(
            "SKU segment to append when this free-value field has a non-null value"
            " (e.g., 'CUSTOM' for custom engraving)"
        ),
    )

    # UI ordering: step groups fields into sections, sequence orders fields within a step
    step: Mapped[int] = mapped_column(Integer, default=0, comment="Grouping step for UI sections")
    sequence: Mapped[int] = mapped_column(Integer, default=0, comment="Display order within step")

    # Relationships
    entity_version: Mapped["EntityVersion"] = relationship(back_populates="fields")
    values: Mapped[list["Value"]] = relationship(back_populates="field", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Field id={self.id} name='{self.name}' type={self.data_type.value} is_free_value={self.is_free_value}>"

    def __str__(self) -> str:
        return self.label or self.name


class Value(Base):
    """One option of an option-based `Field` (only used when `Field.is_free_value` is `False`)."""

    __tablename__ = "values"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"))

    value: Mapped[str] = mapped_column(String(255), comment="Internal value")
    label: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Display label for UI")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # SKU generation
    sku_modifier: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="SKU segment for this value (e.g., '16G' for 16GB RAM)"
    )

    # Relationships
    field: Mapped["Field"] = relationship(back_populates="values")

    def __repr__(self) -> str:
        return f"<Value id={self.id} field_id={self.field_id} value='{self.value}' is_default={self.is_default}>"

    def __str__(self) -> str:
        return self.label or self.value


class Rule(Base):
    """Conditional logic targeting a `Field` (and optionally a specific `Value`).

    `conditions` JSON shape:
    `{"criteria": [{"field_id": 1, "operator": "EQUALS", "value": "Red"}, ...]}`.
    """

    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entity_version_id: Mapped[int] = mapped_column(ForeignKey("entity_versions.id"))

    target_field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"))
    target_value_id: Mapped[int | None] = mapped_column(
        ForeignKey("values.id"),
        nullable=True,
        comment="Only used for AVAILABILITY rules: specifies which Value this rule controls",
    )

    rule_type: Mapped[RuleType] = mapped_column(String(50), default=RuleType.AVAILABILITY)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions: Mapped[dict] = mapped_column(JSON, comment="JSON condition criteria")
    error_message: Mapped[str | None] = mapped_column(
        String, nullable=True, comment="Only used for VALIDATION rules: message shown when validation fails"
    )
    set_value: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Only used for CALCULATION rules: value to assign when conditions are met"
    )

    # Relationships
    entity_version: Mapped["EntityVersion"] = relationship(back_populates="rules")
    target_field: Mapped["Field"] = relationship(foreign_keys=[target_field_id])
    target_value: Mapped["Value"] = relationship(foreign_keys=[target_value_id])

    def __repr__(self) -> str:
        return (
            f"<Rule id={self.id} type={self.rule_type.value} "
            f"target_field={self.target_field_id} target_value={self.target_value_id}>"
        )

    def __str__(self) -> str:
        return f"{self.rule_type.value}: {self.description or 'Unnamed rule'}"


class User(Base, AuditMixin):
    """System user; soft-deleted via `is_active=False` rather than row removal."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(String(50), default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    configurations: Mapped[list["Configuration"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", foreign_keys="[Configuration.user_id]"
    )

    @property
    def role_display(self) -> str:
        """Returns the role as a string, handling both Enum and string storage."""
        if hasattr(self.role, "value"):
            return self.role.value
        return str(self.role)

    def __repr__(self) -> str:
        return f"<User id={self.id} email='{self.email}' role={self.role_display} is_active={self.is_active}>"

    def __str__(self) -> str:
        return self.email


class Configuration(Base, AuditMixin):
    """User-saved input state for an `EntityVersion`. UUID PK for secure sharing.

    `data` is a JSON list `[{"field_id": ..., "value": ...}, ...]` re-hydrated
    on every read. FINALIZED rows additionally store a full `CalculationResponse`
    in `snapshot` and can only be soft-deleted (`is_deleted=True`) by ADMIN.
    """

    __tablename__ = "configurations"
    __table_args__ = (
        Index("ix_user_version", "user_id", "entity_version_id"),
        Index("ix_complete", "is_complete"),
        Index("ix_config_status", "status"),
        Index("ix_config_deleted", "is_deleted"),
    )

    # UUID primary key for secure external access
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    entity_version_id: Mapped[int] = mapped_column(ForeignKey("entity_versions.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="User-defined name")

    # Lifecycle status
    status: Mapped[ConfigurationStatus] = mapped_column(
        String(20),
        default=ConfigurationStatus.DRAFT,
        nullable=False,
        comment="Lifecycle status: DRAFT (mutable) or FINALIZED (immutable)",
    )

    is_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, comment="True if all required fields are filled and validation passes"
    )

    generated_sku: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True, comment="Cached generated SKU from last calculation"
    )

    bom_total_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True, index=True, comment="Cached BOM commercial total from last calculation"
    )

    # Soft delete flag
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Soft delete flag for preserving audit trail of FINALIZED records",
    )

    # Pricing
    price_list_id: Mapped[int | None] = mapped_column(
        ForeignKey("price_lists.id", ondelete="SET NULL"),
        nullable=True,
        comment="Price list used for this configuration",
    )
    price_date: Mapped[dt.date | None] = mapped_column(
        Date, nullable=True, comment="Effective price date (set at finalization)"
    )
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Full CalculationResponse snapshot for FINALIZED configs"
    )

    # Payload: list of field inputs
    data: Mapped[list[dict[str, Any]]] = mapped_column(JSON, comment="Raw input data for re-hydration")

    # Relationships
    entity_version: Mapped["EntityVersion"] = relationship(back_populates="configurations")
    owner: Mapped["User"] = relationship(back_populates="configurations", foreign_keys=[user_id])
    price_list: Mapped["PriceList | None"] = relationship(foreign_keys=[price_list_id])
    custom_items: Mapped[list["ConfigurationCustomItem"]] = relationship(
        back_populates="configuration", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Configuration id={self.id} user_id={self.user_id} "
            f"version_id={self.entity_version_id} status={self.status} "
            f"is_complete={self.is_complete} is_deleted={self.is_deleted}>"
        )

    def __str__(self) -> str:
        return self.name or f"Configuration {self.id[:8]}"


class BOMItem(Base):
    """Bill of Materials line item.

    Hierarchy via self-referential `parent_bom_item_id` (TECHNICAL only;
    COMMERCIAL is flat). Pricing and metadata are joined from `PriceList`
    and `CatalogItem` at calculation time.
    """

    __tablename__ = "bom_items"
    __table_args__ = (
        Index("ix_bom_version", "entity_version_id"),
        Index("ix_bom_parent", "parent_bom_item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entity_version_id: Mapped[int] = mapped_column(ForeignKey("entity_versions.id"), nullable=False)
    parent_bom_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("bom_items.id", ondelete="CASCADE"), nullable=True
    )

    bom_type: Mapped[BOMType] = mapped_column(String(20), nullable=False)
    part_number: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("catalog_items.part_number"),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, server_default="1")
    quantity_from_field_id: Mapped[int | None] = mapped_column(
        ForeignKey("fields.id", ondelete="SET NULL"), nullable=True
    )

    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="Ordering among siblings",
    )

    suppress_auto_explode: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="If true, future re-explode operations skip this row",
    )

    # Relationships
    entity_version: Mapped["EntityVersion"] = relationship(back_populates="bom_items")
    parent: Mapped["BOMItem | None"] = relationship(back_populates="children", remote_side="BOMItem.id")
    children: Mapped[list["BOMItem"]] = relationship(back_populates="parent", cascade="all, delete-orphan")
    quantity_field: Mapped["Field | None"] = relationship(foreign_keys=[quantity_from_field_id])
    rules: Mapped[list["BOMItemRule"]] = relationship(back_populates="bom_item", cascade="all, delete-orphan")
    catalog_item: Mapped["CatalogItem"] = relationship(foreign_keys=[part_number])

    def __repr__(self) -> str:
        return (
            f"<BOMItem id={self.id} part_number='{self.part_number}' "
            f"type={self.bom_type} version_id={self.entity_version_id}>"
        )

    def __str__(self) -> str:
        return self.part_number


class BOMItemRule(Base):
    """Conditional inclusion rule for a `BOMItem`.

    Multiple rules on the same item use OR logic; an item with no rules is
    unconditionally included. `conditions` JSON shape matches `Rule.conditions`.
    """

    __tablename__ = "bom_item_rules"
    __table_args__ = (
        Index("ix_bomrule_item", "bom_item_id"),
        Index("ix_bomrule_version", "entity_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    bom_item_id: Mapped[int] = mapped_column(ForeignKey("bom_items.id", ondelete="CASCADE"), nullable=False)
    entity_version_id: Mapped[int] = mapped_column(ForeignKey("entity_versions.id"), nullable=False)

    conditions: Mapped[dict] = mapped_column(JSON, nullable=False, comment="JSON condition criteria")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    bom_item: Mapped["BOMItem"] = relationship(back_populates="rules")
    entity_version: Mapped["EntityVersion"] = relationship()

    def __repr__(self) -> str:
        return f"<BOMItemRule id={self.id} bom_item_id={self.bom_item_id} version_id={self.entity_version_id}>"

    def __str__(self) -> str:
        return self.description or f"BOMItemRule {self.id}"


class EngineeringTemplateItem(Base, AuditMixin):
    """One direct-child edge of an engineering template.

    A template is the set of rows sharing a `parent_part_number` (no header
    table). Cycles are blocked by an application-layer detector;
    `suppress_child_explosion=True` makes the materialized child a leaf even
    if it has its own template.
    """

    __tablename__ = "engineering_template_items"
    __table_args__ = (
        UniqueConstraint(
            "parent_part_number",
            "child_part_number",
            name="uq_eti_parent_child",
        ),
        CheckConstraint(
            "parent_part_number <> child_part_number",
            name="ck_eti_no_self_loop",
        ),
        CheckConstraint("quantity > 0", name="ck_eti_quantity_positive"),
        CheckConstraint("sequence >= 0", name="ck_eti_sequence_nonnegative"),
        Index("ix_eti_parent", "parent_part_number"),
        Index("ix_eti_child", "child_part_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    parent_part_number: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("catalog_items.part_number"),
        nullable=False,
    )
    child_part_number: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("catalog_items.part_number"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="Ordering among siblings within a template",
    )
    suppress_child_explosion: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="If true, the materialized child BOMItem is treated as a leaf",
    )

    # Relationships
    parent_catalog_item: Mapped["CatalogItem"] = relationship(foreign_keys=[parent_part_number])
    child_catalog_item: Mapped["CatalogItem"] = relationship(foreign_keys=[child_part_number])

    def __repr__(self) -> str:
        return (
            f"<EngineeringTemplateItem id={self.id} "
            f"parent='{self.parent_part_number}' child='{self.child_part_number}' "
            f"quantity={self.quantity} sequence={self.sequence}>"
        )

    def __str__(self) -> str:
        return f"{self.parent_part_number} -> {self.child_part_number} x{self.quantity}"


class PriceList(Base, AuditMixin):
    """Global price catalog with temporal validity.

    Header defines a validity bounding box; all items must fall within it.
    """

    __tablename__ = "price_lists"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[dt.date] = mapped_column(Date, nullable=False, server_default="9999-12-31")

    # Relationships
    items: Mapped[list["PriceListItem"]] = relationship(back_populates="price_list", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<PriceList id={self.id} name='{self.name}' valid={self.valid_from}..{self.valid_to}>"

    def __str__(self) -> str:
        return self.name


class PriceListItem(Base, AuditMixin):
    """Priced row inside a `PriceList`; temporal `valid_from`/`valid_to` instead of version numbers.

    No overlapping date ranges per `(price_list_id, part_number)`; item dates
    must fall within the parent `PriceList` bounding box.
    """

    __tablename__ = "price_list_items"
    __table_args__ = (Index("ix_pli_lookup", "price_list_id", "part_number"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    price_list_id: Mapped[int] = mapped_column(ForeignKey("price_lists.id"), nullable=False)
    part_number: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("catalog_items.part_number"),
        nullable=False,
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    valid_from: Mapped[dt.date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # Relationships
    price_list: Mapped["PriceList"] = relationship(back_populates="items")
    catalog_item: Mapped["CatalogItem"] = relationship(foreign_keys=[part_number])

    def __repr__(self) -> str:
        return (
            f"<PriceListItem id={self.id} part_number='{self.part_number}' "
            f"price={self.unit_price} valid={self.valid_from}..{self.valid_to}>"
        )

    def __str__(self) -> str:
        return f"{self.part_number}: {self.unit_price}"


class CatalogItem(Base, AuditMixin):
    """Canonical part identity referenced by BOM items, price-list items, and engineering templates.

    `part_number` is the immutable business key; retire a part via `status=OBSOLETE`
    rather than renaming.
    """

    __tablename__ = "catalog_items"
    __table_args__ = (UniqueConstraint("part_number", name="uq_catalog_items_part_number"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    part_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PC")
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[CatalogItemStatus] = mapped_column(String(20), nullable=False, server_default="ACTIVE")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<CatalogItem id={self.id} part_number='{self.part_number}' status={self.status}>"

    def __str__(self) -> str:
        return f"{self.part_number}: {self.description}"


class ConfigurationCustomItem(Base, AuditMixin):
    """Configuration-scoped, one-off commercial line; escape hatch for non-cataloged parts.

    `custom_key` is server-generated as `CUSTOM-<uuid8>` and immutable.
    Appears only in the commercial BOM output.
    """

    __tablename__ = "configuration_custom_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_cci_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_cci_unit_price_nonnegative"),
        UniqueConstraint("custom_key", name="uq_cci_custom_key"),
        Index("ix_cci_configuration", "configuration_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    configuration_id: Mapped[str] = mapped_column(ForeignKey("configurations.id", ondelete="CASCADE"), nullable=False)
    custom_key: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit_of_measure: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Relationships
    configuration: Mapped["Configuration"] = relationship(back_populates="custom_items")

    def __repr__(self) -> str:
        return (
            f"<ConfigurationCustomItem id={self.id} custom_key='{self.custom_key}' "
            f"configuration_id={self.configuration_id}>"
        )

    def __str__(self) -> str:
        return f"{self.custom_key}: {self.description}"


class RefreshToken(Base):
    """Long-lived token for issuing new access tokens; supports revocation."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_user_active", "user_id", "is_revoked"),
        Index("ix_token_hash", "token_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)

    # Store hash of token for security (don't store plaintext)
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)

    # Expiration and revocation
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit trail
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Optional: track client info for security
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship(foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<RefreshToken id={self.id} user_id={self.user_id} "
            f"is_revoked={self.is_revoked} expires_at={self.expires_at}>"
        )

    def __str__(self) -> str:
        return f"RefreshToken {self.id} for user {self.user_id}"
