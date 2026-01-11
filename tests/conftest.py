import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app
from app.models.domain import (
    Entity, EntityVersion, Field, Value, Rule,
    RuleType, FieldType, VersionStatus,
    User, UserRole
)
from app.core.rate_limit import limiter
from app.core.security import get_password_hash, create_access_token

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
    La sessione viene chiusa dalla fixture db_session, non qui.
    """
    # Reset rate limiter storage before each test to avoid 429 errors
    limiter.reset()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    # Cleanup: rimuove l'override per evitare side effects tra test
    app.dependency_overrides.clear()

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


# ============================================================
# SHARED USER FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def admin_user(db_session):
    """Creates an admin user for tests."""
    user = User(
        email="admin@example.com",
        hashed_password=get_password_hash("AdminPassword123!"),
        role=UserRole.ADMIN,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def admin_headers(admin_user):
    """Auth headers for admin user."""
    token = create_access_token(subject=admin_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def author_user(db_session):
    """Creates an author user for tests."""
    user = User(
        email="author@example.com",
        hashed_password=get_password_hash("AuthorPassword123!"),
        role=UserRole.AUTHOR,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def author_headers(author_user):
    """Auth headers for author user."""
    token = create_access_token(subject=author_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def regular_user(db_session):
    """Creates a regular user for tests."""
    user = User(
        email="user@example.com",
        hashed_password=get_password_hash("UserPassword123!"),
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def user_headers(regular_user):
    """Auth headers for regular user."""
    token = create_access_token(subject=regular_user.id)
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# SHARED ENTITY FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def test_entity(db_session, admin_user):
    """Creates a basic Entity for version tests."""
    entity = Entity(
        name="Test Entity",
        description="Entity for testing",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture(scope="function")
def second_entity(db_session, admin_user):
    """Creates a second Entity for multi-entity tests."""
    entity = Entity(
        name="Second Entity",
        description="Another entity for testing",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


# ============================================================
# SHARED VERSION FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def draft_version(db_session, test_entity, admin_user):
    """Creates a DRAFT version for the test entity."""
    version = EntityVersion(
        entity_id=test_entity.id,
        version_number=1,
        status=VersionStatus.DRAFT,
        changelog="Initial draft",
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


@pytest.fixture(scope="function")
def published_version(db_session, test_entity, admin_user):
    """Creates a PUBLISHED version for the test entity."""
    version = EntityVersion(
        entity_id=test_entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        changelog="Published version",
        published_at=datetime.now(timezone.utc),
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


@pytest.fixture(scope="function")
def archived_version(db_session, test_entity, admin_user):
    """Creates an ARCHIVED version for the test entity."""
    version = EntityVersion(
        entity_id=test_entity.id,
        version_number=1,
        status=VersionStatus.ARCHIVED,
        changelog="Archived version",
        published_at=datetime.now(timezone.utc),
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(version)
    db_session.commit()
    db_session.refresh(version)
    return version


@pytest.fixture(scope="function")
def version_with_data(db_session, test_entity, admin_user):
    """
    Creates a PUBLISHED version with Fields, Values, and Rules.
    Used for testing deep clone functionality.
    """
    version = EntityVersion(
        entity_id=test_entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        changelog="Version with data for clone tests",
        published_at=datetime.now(timezone.utc),
        created_by_id=admin_user.id,
        updated_by_id=admin_user.id
    )
    db_session.add(version)
    db_session.flush()

    # Create Fields
    field_type = Field(
        entity_version_id=version.id,
        name="vehicle_type",
        label="Vehicle Type",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        sequence=1
    )
    field_value = Field(
        entity_version_id=version.id,
        name="vehicle_value",
        label="Vehicle Value",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        sequence=2
    )
    field_optional = Field(
        entity_version_id=version.id,
        name="has_alarm",
        label="Has Alarm",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        sequence=3
    )
    db_session.add_all([field_type, field_value, field_optional])
    db_session.flush()

    # Create Values for field_type
    value_car = Value(field_id=field_type.id, value="CAR", label="Car", is_default=True)
    value_moto = Value(field_id=field_type.id, value="MOTO", label="Motorcycle", is_default=False)
    value_truck = Value(field_id=field_type.id, value="TRUCK", label="Truck", is_default=False)
    db_session.add_all([value_car, value_moto, value_truck])
    db_session.flush()

    # Create Rules
    rule_mandatory = Rule(
        entity_version_id=version.id,
        target_field_id=field_optional.id,
        rule_type=RuleType.MANDATORY.value,
        description="Alarm mandatory if value > 50000",
        conditions={"criteria": [{"field_id": field_value.id, "operator": "GREATER_THAN", "value": 50000}]},
        error_message="Alarm is required for high-value vehicles"
    )
    rule_visibility = Rule(
        entity_version_id=version.id,
        target_field_id=field_optional.id,
        rule_type=RuleType.VISIBILITY.value,
        description="Hide alarm for motorcycles",
        conditions={"criteria": [{"field_id": field_type.id, "operator": "NOT_EQUALS", "value": "MOTO"}]}
    )
    db_session.add_all([rule_mandatory, rule_visibility])
    db_session.commit()

    db_session.refresh(version)

    return {
        "version": version,
        "fields": {
            "type": field_type,
            "value": field_value,
            "optional": field_optional
        },
        "values": {
            "car": value_car,
            "moto": value_moto,
            "truck": value_truck
        },
        "rules": {
            "mandatory": rule_mandatory,
            "visibility": rule_visibility
        }
    }


# ============================================================
# FIELD FIXTURES (Phase 3)
# ============================================================

@pytest.fixture(scope="function")
def draft_field(db_session, draft_version):
    """Creates a basic field in a DRAFT version."""
    field = Field(
        entity_version_id=draft_version.id,
        name="test_field",
        label="Test Field",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1
    )
    db_session.add(field)
    db_session.commit()
    db_session.refresh(field)
    return field


@pytest.fixture(scope="function")
def free_field(db_session, draft_version):
    """Creates a free-value field in a DRAFT version."""
    field = Field(
        entity_version_id=draft_version.id,
        name="free_text_field",
        label="Free Text Field",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=False,
        default_value="default",
        step=1,
        sequence=2
    )
    db_session.add(field)
    db_session.commit()
    db_session.refresh(field)
    return field


@pytest.fixture(scope="function")
def field_with_values(db_session, draft_version):
    """Creates a non-free field with associated values."""
    field = Field(
        entity_version_id=draft_version.id,
        name="field_with_options",
        label="Field With Options",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1
    )
    db_session.add(field)
    db_session.flush()

    values = [
        Value(field_id=field.id, value="OPTION_A", label="Option A", is_default=True),
        Value(field_id=field.id, value="OPTION_B", label="Option B", is_default=False),
        Value(field_id=field.id, value="OPTION_C", label="Option C", is_default=False),
    ]
    db_session.add_all(values)
    db_session.commit()
    db_session.refresh(field)

    return {"field": field, "values": values}


@pytest.fixture(scope="function")
def field_as_rule_target(db_session, draft_version):
    """Creates a field that is the target of a rule."""
    target_field = Field(
        entity_version_id=draft_version.id,
        name="target_field",
        label="Target Field",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=1
    )
    condition_field = Field(
        entity_version_id=draft_version.id,
        name="condition_field",
        label="Condition Field",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=2
    )
    db_session.add_all([target_field, condition_field])
    db_session.flush()

    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=target_field.id,
        rule_type=RuleType.MANDATORY.value,
        description="Target field mandatory if condition > 100",
        conditions={"criteria": [{"field_id": condition_field.id, "operator": "GREATER_THAN", "value": 100}]},
        error_message="Field is required"
    )
    db_session.add(rule)
    db_session.commit()

    return {
        "target_field": target_field,
        "condition_field": condition_field,
        "rule": rule
    }


@pytest.fixture(scope="function")
def published_field(db_session, published_version):
    """Creates a field in a PUBLISHED version (immutable)."""
    field = Field(
        entity_version_id=published_version.id,
        name="published_field",
        label="Published Field",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1
    )
    db_session.add(field)
    db_session.commit()
    db_session.refresh(field)
    return field


# ============================================================
# VALUE FIXTURES (Phase 3)
# ============================================================

@pytest.fixture(scope="function")
def draft_value(db_session, draft_field):
    """Creates a value attached to a field in DRAFT version."""
    value = Value(
        field_id=draft_field.id,
        value="TEST_VALUE",
        label="Test Value",
        is_default=False
    )
    db_session.add(value)
    db_session.commit()
    db_session.refresh(value)
    return value


@pytest.fixture(scope="function")
def value_in_rule_target(db_session, draft_version):
    """Creates a value that is the explicit target of a rule."""
    field = Field(
        entity_version_id=draft_version.id,
        name="field_for_value_rule",
        label="Field For Value Rule",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1
    )
    db_session.add(field)
    db_session.flush()

    value = Value(field_id=field.id, value="TARGETED", label="Targeted Value", is_default=False)
    other_value = Value(field_id=field.id, value="OTHER", label="Other Value", is_default=True)
    db_session.add_all([value, other_value])
    db_session.flush()

    # Condition field
    cond_field = Field(
        entity_version_id=draft_version.id,
        name="condition_for_value",
        label="Condition For Value",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=2
    )
    db_session.add(cond_field)
    db_session.flush()

    cond_value = Value(field_id=cond_field.id, value="TRIGGER", label="Trigger", is_default=True)
    db_session.add(cond_value)
    db_session.flush()

    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=field.id,
        target_value_id=value.id,
        rule_type=RuleType.AVAILABILITY.value,
        description="Value available only if trigger",
        conditions={"criteria": [{"field_id": cond_field.id, "value_id": cond_value.id, "operator": "EQUALS", "value": "TRIGGER"}]}
    )
    db_session.add(rule)
    db_session.commit()

    return {
        "field": field,
        "value": value,
        "other_value": other_value,
        "condition_field": cond_field,
        "condition_value": cond_value,
        "rule": rule
    }


@pytest.fixture(scope="function")
def value_in_rule_condition(db_session, draft_version):
    """Creates a value that is used in a rule's condition criteria."""
    # Field with value used as condition
    condition_field = Field(
        entity_version_id=draft_version.id,
        name="condition_source_field",
        label="Condition Source",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1
    )
    db_session.add(condition_field)
    db_session.flush()

    condition_value = Value(field_id=condition_field.id, value="CONDITION_VAL", label="Condition Value", is_default=True)
    db_session.add(condition_value)
    db_session.flush()

    # Target field
    target_field = Field(
        entity_version_id=draft_version.id,
        name="affected_field",
        label="Affected Field",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=2
    )
    db_session.add(target_field)
    db_session.flush()

    # Rule that uses condition_value in its criteria
    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=target_field.id,
        rule_type=RuleType.VISIBILITY.value,
        description="Show if condition value selected",
        conditions={"criteria": [{"field_id": condition_field.id, "value_id": condition_value.id, "operator": "EQUALS", "value": "CONDITION_VAL"}]}
    )
    db_session.add(rule)
    db_session.commit()

    return {
        "condition_field": condition_field,
        "condition_value": condition_value,
        "target_field": target_field,
        "rule": rule
    }


# ============================================================
# RULE FIXTURES (Phase 3)
# ============================================================

@pytest.fixture(scope="function")
def draft_rule(db_session, draft_version):
    """Creates a basic rule in a DRAFT version."""
    target_field = Field(
        entity_version_id=draft_version.id,
        name="rule_target",
        label="Rule Target",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=1
    )
    source_field = Field(
        entity_version_id=draft_version.id,
        name="rule_source",
        label="Rule Source",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=2
    )
    db_session.add_all([target_field, source_field])
    db_session.flush()

    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=target_field.id,
        rule_type=RuleType.MANDATORY.value,
        description="Basic test rule",
        conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]},
        error_message="Must be positive"
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    return {
        "rule": rule,
        "target_field": target_field,
        "source_field": source_field
    }


@pytest.fixture(scope="function")
def published_rule(db_session, published_version):
    """Creates a rule in a PUBLISHED version (immutable)."""
    target_field = Field(
        entity_version_id=published_version.id,
        name="pub_rule_target",
        label="Published Rule Target",
        data_type=FieldType.BOOLEAN.value,
        is_free_value=True,
        is_required=False,
        step=1,
        sequence=1
    )
    source_field = Field(
        entity_version_id=published_version.id,
        name="pub_rule_source",
        label="Published Rule Source",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=2
    )
    db_session.add_all([target_field, source_field])
    db_session.flush()

    rule = Rule(
        entity_version_id=published_version.id,
        target_field_id=target_field.id,
        rule_type=RuleType.VISIBILITY.value,
        description="Published rule",
        conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    return {"rule": rule, "target_field": target_field, "source_field": source_field}


@pytest.fixture(scope="function")
def rule_with_value_target(db_session, draft_version):
    """Creates a rule that targets a specific value (AVAILABILITY rule)."""
    field = Field(
        entity_version_id=draft_version.id,
        name="availability_field",
        label="Availability Field",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=True,
        step=1,
        sequence=1
    )
    source_field = Field(
        entity_version_id=draft_version.id,
        name="availability_source",
        label="Availability Source",
        data_type=FieldType.NUMBER.value,
        is_free_value=True,
        is_required=True,
        step=1,
        sequence=2
    )
    db_session.add_all([field, source_field])
    db_session.flush()

    value1 = Value(field_id=field.id, value="VAL1", label="Value 1", is_default=True)
    value2 = Value(field_id=field.id, value="VAL2", label="Value 2", is_default=False)
    db_session.add_all([value1, value2])
    db_session.flush()

    rule = Rule(
        entity_version_id=draft_version.id,
        target_field_id=field.id,
        target_value_id=value2.id,
        rule_type=RuleType.AVAILABILITY.value,
        description="Value 2 availability rule",
        conditions={"criteria": [{"field_id": source_field.id, "operator": "GREATER_THAN", "value": 0}]}
    )
    db_session.add(rule)
    db_session.commit()

    return {
        "field": field,
        "source_field": source_field,
        "value1": value1,
        "value2": value2,
        "rule": rule
    }