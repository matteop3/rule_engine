# app/models/domain.py
from typing import List, Dict, Optional, Any
from sqlalchemy import String, Boolean, ForeignKey, Integer, Text, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from app.database import Base
import enum
import uuid


# --- ENUMS ---
class VersionStatus(str, enum.Enum):
    DRAFT = "DRAFT"         # On working, editable
    PUBLISHED = "PUBLISHED" # Active, read-only, used by the engine
    ARCHIVED = "ARCHIVED"   # Old, read-only, preserved for history


class UserRole(str, enum.Enum):
    ADMIN = "admin"     # God-user (all permissions)
    AUTHOR = "author"   # Product manager (manage everything except for users)
    USER = "user"       # Regular user (use configurator and manage own Configurations)


class FieldType(str, enum.Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"


# --- MIXINS ---
class AuditMixin:
    """ Add creation and editing automatic tracking. """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=func.now(), 
        nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), 
        onupdate=func.now(), 
        nullable=True
    )
    created_by_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)


# --- TABLES ---
class Entity(Base, AuditMixin):
    """ Entities logical container. """
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relation 1-to-N with its versions
    versions: Mapped[List["EntityVersion"]] = relationship(back_populates="entity", cascade="all, delete-orphan")


class EntityVersion(Base, AuditMixin):
    """
    A specific snapshot of the Entity configuration. 
    It contains the Fields and Rules valid for this version.
    """
    __tablename__ = "entity_versions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[VersionStatus] = mapped_column(String(20), default=VersionStatus.DRAFT)
    changelog: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relations
    entity: Mapped["Entity"] = relationship(back_populates="versions")
    fields: Mapped[List["Field"]] = relationship(back_populates="entity_version", cascade="all, delete-orphan")
    rules: Mapped[List["Rule"]] = relationship(back_populates="entity_version", cascade="all, delete-orphan")

    # By deleting a DRAFT Version all associated Configurations are deleted.
    configurations: Mapped[List["Configuration"]] = relationship(back_populates="entity_version", cascade="all, delete-orphan")


class Field(Base):
    """ Represents a choice of an Entity. """
    __tablename__ = "fields"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entity_version_id: Mapped[int] = mapped_column(ForeignKey("entity_versions.id"))
    
    name: Mapped[str] = mapped_column(String(100))
    data_type: Mapped[str] = mapped_column(String(50), default="string")
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_readonly: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    is_free_value: Mapped[bool] = mapped_column(Boolean, default=False)    
    default_value: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Ordering purpose
    step: Mapped[int] = mapped_column(Integer, default=0)
    sequence: Mapped[int] = mapped_column(Integer, default=0)

    # Relations
    entity_version: Mapped["EntityVersion"] = relationship(back_populates="fields")
    values: Mapped[List["Value"]] = relationship(back_populates="field", cascade="all, delete-orphan")


class Value(Base):
    """ Represents a possible value of a specific Field. """
    __tablename__ = "values"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"))
    
    value: Mapped[str] = mapped_column(String(255))
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relations
    field: Mapped["Field"] = relationship(back_populates="values")


class Rule(Base):
    """
    Represents a specific condition to make a Value 
    avalable or a Field visible and editable.
    """
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entity_version_id: Mapped[int] = mapped_column(ForeignKey("entity_versions.id"))
    
    target_field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"))
    target_value_id: Mapped[Optional[int]] = mapped_column(ForeignKey("values.id"), nullable=True)
    
    rule_type: Mapped[str] = mapped_column(String(50), default="availability")    
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conditions: Mapped[dict] = mapped_column(JSON)

    # Relations
    entity_version: Mapped["EntityVersion"] = relationship(back_populates="rules")
    target_field: Mapped["Field"] = relationship(foreign_keys=[target_field_id])
    target_value: Mapped["Value"] = relationship(foreign_keys=[target_value_id])


class User(Base, AuditMixin):
    """ Represents a user of the systems. """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    
    role: Mapped[UserRole] = mapped_column(String(50), default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relations
    configurations: Mapped[List["Configuration"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Configuration(Base, AuditMixin):
    """
    Stores a user's session/quote.
    Uses UUID for secure external access.
    Stores raw input data (re-hydration strategy).
    """
    __tablename__ = "configurations"

    # UUID primary key
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    entity_version_id: Mapped[int] = mapped_column(ForeignKey("entity_versions.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Payload: list of inputs [{"field_id": 1, "value": "Red"}, ...]
    data: Mapped[List[Dict[str, Any]]] = mapped_column(JSON)

    # Relations
    entity_version: Mapped["EntityVersion"] = relationship(back_populates="configurations")
    owner: Mapped["User"] = relationship(back_populates="configurations")