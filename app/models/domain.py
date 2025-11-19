from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column, declarative_base
from app.database import Base # Importo Base da database.py

# --- Struttura ---

class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)


class Field(Base):
    __tablename__ = "fields"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)


class Value(Base):
    __tablename__ = "values"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)


class Rule(Base):
    __tablename__ = "rules"
    id: Mapped[int] = mapped_column(primary_key=True, index=True)