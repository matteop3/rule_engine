# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings

# create_engine: Punto di ingresso per il DB.
# connect_args={"check_same_thread": False} è NECESSARIO solo per SQLite.
# SQLite di default permette l'accesso solo al thread che lo ha creato.
# Poiché FastAPI è multithreaded, dobbiamo disabilitare questo controllo.
engine = create_engine(
    settings.DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# SessionLocal: È una "factory". Ogni volta che la chiamiamo, crea una nuova sessione DB.
# Non è la sessione stessa, ma la classe per crearle.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# DEFINIZIONE UNICA DELLA BASE
class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()