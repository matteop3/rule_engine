from typing import List, Optional
from sqlalchemy import ForeignKey, String, Integer, Boolean, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    # Relations: one Entity has many fields and rules
    fields: Mapped[List["Field"]] = relationship(back_populates="entity", cascade="all, delete-orphan")
    rules: Mapped[List["Rule"]] = relationship(back_populates="entity", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Entity(name={self.name})>"


class Field(Base):
    __tablename__ = "fields"

    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(100))
    data_type: Mapped[str] = mapped_column(String(50), default="string")
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_free_value: Mapped[bool] = mapped_column(Boolean, default=False)
    step: Mapped[int] = mapped_column(Integer, default=0) 
    sequence: Mapped[int] = mapped_column(Integer, default=0)

    # Relations
    entity: Mapped["Entity"] = relationship(back_populates="fields")
    values: Mapped[Optional[List["Value"]]] = relationship(back_populates="field", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Field(name={self.name}, entity={self.entity.name})>"


class Value(Base):
    __tablename__ = "values"

    field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"))
    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    is_default: Mapped[bool] = mapped_column(Boolean, default=False)    
    value: Mapped[str] = mapped_column(String(255)) # Save the value as a string for generality. Casting will take place in the service layer based on field.data_type.
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relations
    field: Mapped["Field"] = relationship(back_populates="values")

    def __repr__(self):
        return f"<Value({self.value}, field={self.field.name})>"


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    
    # This rule enable this specific target value
    target_field_id: Mapped[int] = mapped_column(ForeignKey("fields.id"))
    target_value_id: Mapped[int] = mapped_column(ForeignKey("values.id"))

    # Conditions logic stored as JSON
    conditions: Mapped[dict] = mapped_column(JSON)

    entity: Mapped["Entity"] = relationship(back_populates="rules")
    # Relazioni opzionali per navigazione facile, se servono
    target_field: Mapped["Field"] = relationship(foreign_keys=[target_field_id])
    target_value: Mapped["Value"] = relationship(foreign_keys=[target_value_id])