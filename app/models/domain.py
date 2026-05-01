"""
Domain Models for Rule Engine.

This module defines the core SQLAlchemy ORM models for the rule engine system:

Entities:
    - Entity: Logical containers for versioned configurations
    - EntityVersion: Versioned snapshots with Fields and Rules
    - Field: Configurable properties of entities
    - Value: Possible values for Fields
    - Rule: Business logic rules that control field behavior
    - User: System users with role-based access control
    - Configuration: User-saved configuration snapshots
    - PriceList: Global price catalogs with temporal validity
    - PriceListItem: Priced components within a PriceList

Enums:
    - VersionStatus: Lifecycle states (DRAFT, PUBLISHED, ARCHIVED)
    - UserRole: Access control roles (ADMIN, AUTHOR, USER)
    - FieldType: Data types for fields (STRING, NUMBER, BOOLEAN, DATE)
    - RuleType: Rule categories (VISIBILITY, AVAILABILITY, EDITABILITY, MANDATORY, VALIDATION)

All models use SQLAlchemy 2.0 Mapped syntax with type hints for improved type safety.
The AuditMixin provides automatic tracking of creation/update timestamps and users.
"""

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
    """
    Lifecycle status for EntityVersion.

    - DRAFT: Work in progress, editable by ADMIN/AUTHOR
    - PUBLISHED: Active version, read-only, used by rule engine
    - ARCHIVED: Historical version, read-only, preserved for audit trail
    """

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class UserRole(str, enum.Enum):
    """
    Role-based access control levels.

    - ADMIN: Full system access (all permissions including user management)
    - AUTHOR: Product manager (manage entities, versions, rules)
    - USER: Regular user (use configurator and manage own configurations)
    """

    ADMIN = "admin"
    AUTHOR = "author"
    USER = "user"


class ConfigurationStatus(str, enum.Enum):
    """
    Lifecycle status for Configuration records.

    This enum manages the technical mutability state of configurations,
    focusing on data integrity rather than business workflow states.

    - DRAFT: Work in progress (Sandbox). The configuration is mutable:
             user can modify inputs, upgrade version, or delete the record.
             Conceptually represents an open cart or a quote draft.

    - FINALIZED: Consolidated snapshot (Read-Only). The configuration is
                 immutable for legal and technical reproducibility.
                 No modifications to inputs or version are allowed.
                 Conceptually represents an issued quote or submitted order.
    """

    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class FieldType(str, enum.Enum):
    """
    Data types for Field values.

    Defines the expected type of user input for a field.
    """

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"


class RuleType(str, enum.Enum):
    """
    Categories of business logic rules.

    - VISIBILITY: Controls whether a field is shown or hidden
    - AVAILABILITY: Filters available options for multi-choice fields
    - CALCULATION: Sets a field's value and makes it implicitly readonly
    - EDITABILITY: Controls whether a field is read-only or writable
    - MANDATORY: Controls whether a field is required or optional
    - VALIDATION: Validates field content against business rules
    """

    VISIBILITY = "visibility"
    AVAILABILITY = "availability"
    CALCULATION = "calculation"
    EDITABILITY = "editability"
    MANDATORY = "mandatory"
    VALIDATION = "validation"


class CatalogItemStatus(str, enum.Enum):
    """
    Lifecycle status for CatalogItem.

    - ACTIVE: Can be referenced by new BOM items and price list items.
    - OBSOLETE: Existing references keep working, but new references are blocked.
    """

    ACTIVE = "ACTIVE"
    OBSOLETE = "OBSOLETE"


class BOMType(str, enum.Enum):
    """
    Bill of Materials item type classification.

    - TECHNICAL: Engineering/assembly BOM — no pricing, supports hierarchy (sub-assemblies)
    - COMMERCIAL: Sales/pricing BOM — pricing resolved from price list, always root-level (flat list)

    A component appearing in both lists is modeled as two separate BOM items
    with the same part_number — one TECHNICAL and one COMMERCIAL.
    """

    TECHNICAL = "TECHNICAL"
    COMMERCIAL = "COMMERCIAL"


# ============================================================
# MIXINS
# ============================================================


class AuditMixin:
    """
    Provides automatic audit trail tracking for models.

    Adds timestamp fields (created_at, updated_at) and user tracking
    (created_by_id, updated_by_id) to any model that inherits this mixin.

    Timestamps are automatically managed by SQLAlchemy:
    - created_at: Set on insert via server_default
    - updated_at: Set on update via onupdate
    """

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
    """
    Entity: Logical container for versioned configurations.

    An Entity represents a configurable product or domain object (e.g., "Car", "Laptop").
    Each Entity can have multiple versions to support iterative development and A/B testing.

    Relationships:
        - versions: One-to-many with EntityVersion (cascade delete)
    """

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
    """
    EntityVersion: A specific snapshot of an Entity's configuration.

    Represents a version of an Entity with its associated Fields and Rules.
    Supports versioning workflow: DRAFT → PUBLISHED → ARCHIVED.
    Only one PUBLISHED version per Entity is allowed at a time.

    Relationships:
        - entity: Many-to-one with Entity
        - fields: One-to-many with Field (cascade delete)
        - rules: One-to-many with Rule (cascade delete)
        - configurations: One-to-many with Configuration (cascade delete)
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
    """
    Field: Represents a configurable property of an Entity.

    A Field can be either:
    - Free-value: User enters arbitrary text (default_value on Field)
    - Option-based: User selects from predefined Values (default via Value.is_default)

    Relationships:
        - entity_version: Many-to-one with EntityVersion
        - values: One-to-many with Value (cascade delete)
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
    """
    Value: Represents a possible option for an option-based Field.

    Values are only used when Field.is_free_value is False.
    One Value can be marked as default via is_default flag.

    Relationships:
        - field: Many-to-one with Field
    """

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
    """
    Rule: Business logic that controls Field and Value behavior.

    Rules define conditional logic to control field visibility, availability,
    editability, mandatory state, or validation based on other field values.

    Condition structure: {"criteria": [{"field_id": 1, "operator": "EQUALS", "value": "Red"}, ...]}

    Relationships:
        - entity_version: Many-to-one with EntityVersion
        - target_field: Many-to-one with Field (the field this rule affects)
        - target_value: Many-to-one with Value (optional, specific value this rule affects)
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
    """
    User: System user with role-based access control.

    Users authenticate via email/password and have one of three roles:
    ADMIN, AUTHOR, or USER (see UserRole enum for details).

    Soft delete: is_active=False instead of actual deletion.

    Relationships:
        - configurations: One-to-many with Configuration (cascade delete)
    """

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
    """
    Configuration: User-saved configuration snapshot.

    Stores a user's input state for a specific EntityVersion.
    Uses UUID for secure external access (shareable links).
    Stores raw input data as JSON for re-hydration strategy.

    Data format: [{"field_id": 1, "value": "Red"}, {"field_id": 2, "value": "Large"}, ...]

    Status Lifecycle:
        - DRAFT: Mutable sandbox state. User can modify inputs, upgrade version, or delete.
        - FINALIZED: Immutable snapshot. Read-only for legal/technical reproducibility.

    Soft Delete:
        - is_deleted flag allows logical deletion without losing audit trail
        - FINALIZED configurations can only be soft-deleted by ADMIN

    Relationships:
        - entity_version: Many-to-one with EntityVersion
        - owner: Many-to-one with User
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
    """
    BOMItem: Bill of Materials line item for an EntityVersion.

    Represents a component, part, or sub-assembly in the product structure.
    Supports hierarchical nesting via self-referential parent relationship.
    Quantity can be static or dynamically resolved from a field value at evaluation time.
    Pricing is resolved at calculation time from the price list, not stored on the BOM item.

    Relationships:
        - entity_version: Many-to-one with EntityVersion (cascade delete from version)
        - parent: Many-to-one self-referential (cascade delete children)
        - children: One-to-many self-referential
        - quantity_field: Many-to-one with Field (SET NULL on field deletion — falls back to static quantity)
        - rules: One-to-many with BOMItemRule (cascade delete)
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
    """
    BOMItemRule: Conditional inclusion rule for a BOM item.

    Controls whether a BOM item is included in the output based on field conditions.
    Multiple rules on the same BOM item use OR logic (item included if any rule passes).
    BOM items with no rules are unconditionally included.

    Condition structure: {"criteria": [{"field_id": 1, "operator": "EQUALS", "value": "Red"}, ...]}

    Relationships:
        - bom_item: Many-to-one with BOMItem (cascade delete)
        - entity_version: Many-to-one with EntityVersion
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
    """
    EngineeringTemplateItem: One direct-child relationship within an engineering template.

    A "template" is the set of all `EngineeringTemplateItem` rows sharing a
    `parent_part_number`; there is no separate header table. Templates describe
    the canonical engineering structure of composite parts and are exploded
    recursively when materializing a TECHNICAL `BOMItem` sub-tree.

    The pair `(parent_part_number, child_part_number)` is unique within the
    template; longer cycles are blocked at the application layer by the cycle
    detector. The `suppress_child_explosion` flag instructs the materialization
    service to treat the resulting `BOMItem` as a leaf even when the child part
    has its own template.

    Relationships:
        - parent_catalog_item: Many-to-one with CatalogItem (parent_part_number)
        - child_catalog_item: Many-to-one with CatalogItem (child_part_number)
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
    """
    PriceList: Global price catalog with temporal validity.

    Price lists are standalone entities decoupled from any specific Entity or EntityVersion.
    The header defines a validity bounding box; all items must fall within this range.

    Relationships:
        - items: One-to-many with PriceListItem (cascade delete)
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
    """
    PriceListItem: A priced component within a PriceList.

    Uses temporal validity (valid_from/valid_to) for versioning instead of explicit
    version numbers. For a given (price_list_id, part_number), no two items may have
    overlapping date ranges.

    Item dates must fall within the parent PriceList's bounding box.

    Relationships:
        - price_list: Many-to-one with PriceList
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
    """
    Catalog of part identities referenced by BOM items and price list items.

    Holds the canonical metadata for each part number: description,
    unit of measure, category, lifecycle status, and free-form notes.
    The `part_number` is the business key and is immutable after creation;
    to retire a part, set its `status` to OBSOLETE rather than renaming it.
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
    """
    Configuration-scoped, one-off commercial line item.

    Exists outside the catalog as an escape hatch for parts that are not yet
    coded. Tied to a single `Configuration` via FK with cascade delete.
    The `custom_key` is server-generated as ``CUSTOM-<uuid8>`` and is stable
    for the lifetime of the row, so future retroactive classification can
    reference it. Appears only in the commercial BOM output.
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
    """
    RefreshToken: Long-lived token for obtaining new access tokens.

    Stores refresh tokens with expiration and revocation support.
    Each token is unique and can be revoked individually for security.

    Relationships:
        - user: Many-to-one with User
    """

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
