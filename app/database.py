# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# In produzione, questo URL verrebbe letto da app/core/config.py o variabili d'ambiente
SQLALCHEMY_DATABASE_URL = "sqlite:///./rule_engine.db"

# create_engine: Punto di ingresso per il DB.
# connect_args={"check_same_thread": False} è NECESSARIO solo per SQLite.
# SQLite di default permette l'accesso solo al thread che lo ha creato.
# Poiché FastAPI è multithreaded, dobbiamo disabilitare questo controllo.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False} 
)

# SessionLocal: È una "factory". Ogni volta che la chiamiamo, crea una nuova sessione DB.
# Non è la sessione stessa, ma la classe per crearle.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base: Classe da cui erediteranno tutti i nostri modelli ORM (Entity, Field, Rule).
Base = declarative_base()

# Dependency Injection per FastAPI
def get_db():
    """
    Generatore che crea una sessione DB per ogni richiesta e la chiude al termine.
    Garantisce che non lasciamo connessioni appese.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()