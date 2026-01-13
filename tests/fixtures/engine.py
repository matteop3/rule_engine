"""
Rule Engine scenario fixtures for tests.
Provides complex pre-configured scenarios for engine logic testing.
"""
import pytest
from datetime import date
from sqlalchemy.orm import Session
from app.models.domain import (
    Entity, EntityVersion, Field, Value, Rule,
    RuleType, FieldType, VersionStatus
)


@pytest.fixture(scope="function")
def setup_insurance_scenario(db_session: Session):
    """
    Populates the DB with the Auto Insurance Gold scenario for tests.

    Includes:
    - Fields: nome, nascita, tipo veicolo, valore, satellitare, massimale, infortuni
    - Values: AUTO/MOTO/CAMION, MINIMO/VIP
    - Rules: minorenne validation, mandatory satellitare, visibility infortuni, availability massimale
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

    # Fields (Using the same as the real seed)
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


@pytest.fixture(scope="function")
def setup_dropdown_scenario(db_session):
    """
    Scenario: Regione -> Città (cascading dropdowns).

    Regione: [Nord, Sud]
    Città: [Milano, Torino, Napoli, Palermo]

    Regole:
    - Se Regione == Nord -> Solo Milano, Torino disponibili
    - Se Regione == Sud -> Solo Napoli, Palermo disponibili
    """
    entity = Entity(name="Dropdown Test", description="Cascading menus")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # 1. Campo Regione (Dropdown)
    f_region = Field(entity_version_id=version.id, name="region", label="Regione", data_type="string", sequence=1, is_free_value=False)
    db_session.add(f_region)
    db_session.commit()

    # Region values
    v_north = Value(field_id=f_region.id, value="NORD", label="Nord Italia")
    v_south = Value(field_id=f_region.id, value="SUD", label="Sud Italia")
    db_session.add_all([v_north, v_south])

    # 2. Campo Città (Dropdown)
    f_city = Field(entity_version_id=version.id, name="city", label="Città", data_type="string", sequence=2, is_free_value=False)
    db_session.add(f_city)
    db_session.commit()

    # City values
    v_milano = Value(field_id=f_city.id, value="MILANO", label="Milano")
    v_torino = Value(field_id=f_city.id, value="TORINO", label="Torino")
    v_napoli = Value(field_id=f_city.id, value="NAPOLI", label="Napoli")
    v_palermo = Value(field_id=f_city.id, value="PALERMO", label="Palermo")
    db_session.add_all([v_milano, v_torino, v_napoli, v_palermo])
    db_session.commit()

    # 3. Availability rules (Filter)
    # "Milano is available ONLY IF Region == NORD"
    r_milano = Rule(
        entity_version_id=version.id, target_field_id=f_city.id, target_value_id=v_milano.id,
        rule_type=RuleType.AVAILABILITY.value,
        conditions={"criteria": [{"field_id": f_region.id, "operator": "EQUALS", "value": "NORD"}]}
    )
    # "Napoli is available ONLY IF Region == SUD"
    r_napoli = Rule(
        entity_version_id=version.id, target_field_id=f_city.id, target_value_id=v_napoli.id,
        rule_type=RuleType.AVAILABILITY.value,
        conditions={"criteria": [{"field_id": f_region.id, "operator": "EQUALS", "value": "SUD"}]}
    )

    db_session.add_all([r_milano, r_napoli])
    db_session.commit()

    return {
        "e_id": entity.id,
        "f_region": f_region.id,
        "f_city": f_city.id,
        "val_milano": v_milano.id
    }


@pytest.fixture(scope="function")
def setup_operator_scenario(db_session):
    """
    Generic scenario for testing all operators.

    Includes fields of various types:
    - string_field (free text)
    - number_field (free number)
    - date_field (free date)
    - dropdown_field with multiple values
    """
    entity = Entity(name="Operator Test", description="Testing operators")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # Fields
    f_string = Field(
        entity_version_id=version.id, name="string_field", label="String Field",
        data_type=FieldType.STRING.value, sequence=1, is_free_value=True
    )
    f_number = Field(
        entity_version_id=version.id, name="number_field", label="Number Field",
        data_type=FieldType.NUMBER.value, sequence=2, is_free_value=True
    )
    f_date = Field(
        entity_version_id=version.id, name="date_field", label="Date Field",
        data_type=FieldType.DATE.value, sequence=3, is_free_value=True
    )
    f_dropdown = Field(
        entity_version_id=version.id, name="dropdown_field", label="Dropdown",
        data_type=FieldType.STRING.value, sequence=4, is_free_value=False
    )

    db_session.add_all([f_string, f_number, f_date, f_dropdown])
    db_session.commit()

    # Dropdown values
    v_opt1 = Value(field_id=f_dropdown.id, value="OPTION1", label="Option 1")
    v_opt2 = Value(field_id=f_dropdown.id, value="OPTION2", label="Option 2")
    v_opt3 = Value(field_id=f_dropdown.id, value="OPTION3", label="Option 3")
    db_session.add_all([v_opt1, v_opt2, v_opt3])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {
            "string": f_string.id,
            "number": f_number.id,
            "date": f_date.id,
            "dropdown": f_dropdown.id
        },
        "values": {
            "opt1": v_opt1.id,
            "opt2": v_opt2.id,
            "opt3": v_opt3.id
        }
    }


@pytest.fixture(scope="function")
def setup_stress_scenario(db_session):
    """
    Complex scenario with cascading dependencies for stress testing.

    Multiple fields with interdependent rules to test:
    - Domino effects (A affects B affects C)
    - Circular logic prevention
    - Multiple validation rules on same field
    """
    entity = Entity(name="Stress Test", description="Complex rule interactions")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # Create 5 interdependent fields
    fields = []
    for i in range(1, 6):
        field = Field(
            entity_version_id=version.id,
            name=f"field_{i}",
            label=f"Field {i}",
            data_type=FieldType.NUMBER.value,
            sequence=i,
            is_free_value=True,
            is_required=False
        )
        fields.append(field)
        db_session.add(field)

    db_session.commit()

    # Create cascading rules
    # Field 2 mandatory if Field 1 > 10
    r1 = Rule(
        entity_version_id=version.id,
        target_field_id=fields[1].id,
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": fields[0].id, "operator": "GREATER_THAN", "value": 10}]}
    )

    # Field 3 visible only if Field 2 > 5
    r2 = Rule(
        entity_version_id=version.id,
        target_field_id=fields[2].id,
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": fields[1].id, "operator": "GREATER_THAN", "value": 5}]}
    )

    # Field 4 validation: must be less than Field 3
    r3 = Rule(
        entity_version_id=version.id,
        target_field_id=fields[3].id,
        rule_type=RuleType.VALIDATION.value,
        error_message="Field 4 must be less than Field 3",
        conditions={"criteria": [
            {"field_id": fields[2].id, "operator": "GREATER_THAN", "value": "{{field_4}}"}
        ]}
    )

    db_session.add_all([r1, r2, r3])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {f"field_{i+1}": f.id for i, f in enumerate(fields)}
    }
