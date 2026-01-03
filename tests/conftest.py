import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.models.domain import Entity, EntityVersion, Field, Value, Rule, RuleType, FieldType, VersionStatus

# 1. SETUP DATABASE IN-MEMORY (Volatile)
# Usiamo SQLite in memoria per velocità e isolamento totale
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool, # Necessario per in-memory SQLite
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    """
    Crea un nuovo database pulito per ogni singolo test.
    """
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    """
    Client HTTP che sovrascrive la dipendenza get_db per usare il DB di test.
    """
    def override_get_db():
        try:
            yield db_session
        finally:
            db_session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c

# 2. SEED DATA FIXTURE
# Inserisce i dati della Polizza Auto nel DB di test
@pytest.fixture(scope="function")
def setup_insurance_scenario(db_session: Session):
    """
    Popola il DB con lo scenario Polizza Auto Gold per i test.
    """
    # Entity & Version
    entity = Entity(name="Test Polizza", description="Test Desc")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED, changelog="V1"
    )
    db_session.add(version)
    db_session.commit()

    # Fields (Uso gli stessi del tuo seed reale)
    f_nome = Field(entity_version_id=version.id, name="contraente_nome", label="Nome", data_type=FieldType.STRING.value, is_free_value=True, is_required=True)
    f_nascita = Field(entity_version_id=version.id, name="contraente_nascita", label="Nascita", data_type=FieldType.DATE.value, is_free_value=True, is_required=True)
    f_tipo = Field(entity_version_id=version.id, name="veicolo_tipo", label="Tipo", data_type=FieldType.STRING.value, is_free_value=False, is_required=True)
    f_valore = Field(entity_version_id=version.id, name="veicolo_valore", label="Valore", data_type=FieldType.NUMBER.value, is_free_value=True, is_required=True)
    f_satellitare = Field(entity_version_id=version.id, name="veicolo_antifurto", label="Satellitare", data_type=FieldType.BOOLEAN.value, is_free_value=True) # Default optional
    f_massimale = Field(entity_version_id=version.id, name="polizza_massimale", label="Massimale", data_type=FieldType.STRING.value, is_free_value=False, is_required=True)
    f_infortuni = Field(entity_version_id=version.id, name="polizza_infortuni", label="Infortuni", data_type=FieldType.BOOLEAN.value, is_free_value=True)

    db_session.add_all([f_nome, f_nascita, f_tipo, f_valore, f_satellitare, f_massimale, f_infortuni])
    db_session.commit()

    # Values
    v_auto = Value(field_id=f_tipo.id, label="Auto", value="AUTO")
    v_moto = Value(field_id=f_tipo.id, label="Moto", value="MOTO")
    v_camion = Value(field_id=f_tipo.id, label="Camion", value="CAMION")
    
    v_mass_min = Value(field_id=f_massimale.id, label="Min", value="MINIMO")
    v_mass_vip = Value(field_id=f_massimale.id, label="Vip", value="VIP")

    db_session.add_all([v_auto, v_moto, v_camion, v_mass_min, v_mass_vip])
    db_session.commit()

    # Rules
    # 1. Validation Minorenne
    from datetime import date
    maggiore_eta = date.today().replace(year=date.today().year - 18)
    r_minorenne = Rule(
        entity_version_id=version.id, target_field_id=f_nascita.id, rule_type=RuleType.VALIDATION.value,
        error_message="Minorenne",
        conditions={"criteria": [{"field_id": f_nascita.id, "operator": "GREATER_THAN", "value": str(maggiore_eta)}]}
    )

    # 2. Mandatory Satellitare se Valore > 50000
    r_mand_sat = Rule(
        entity_version_id=version.id, target_field_id=f_satellitare.id, rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": f_valore.id, "operator": "GREATER_THAN", "value": 50000}]}
    )

    # 3. Visibility Infortuni nascosto se Moto
    r_hide_infortuni = Rule(
        entity_version_id=version.id, target_field_id=f_infortuni.id, rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": f_tipo.id, "operator": "NOT_EQUALS", "value": "MOTO"}]}
    )

    # 4. Availability No Minimo se Camion
    r_no_min_camion = Rule(
        entity_version_id=version.id, target_field_id=f_massimale.id, target_value_id=v_mass_min.id, rule_type=RuleType.AVAILABILITY.value,
        conditions={"criteria": [{"field_id": f_tipo.id, "operator": "NOT_EQUALS", "value": "CAMION"}]}
    )

    db_session.add_all([r_minorenne, r_mand_sat, r_hide_infortuni, r_no_min_camion])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {
            "nascita": f_nascita.id,
            "valore": f_valore.id,
            "satellitare": f_satellitare.id,
            "tipo": f_tipo.id,
            "massimale": f_massimale.id,
            "infortuni": f_infortuni.id
        }
    }