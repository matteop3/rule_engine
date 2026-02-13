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
    - Fields: name, birthdate, vehicle type, value, satellite tracker, coverage, injuries
    - Values: AUTO/MOTO/CAMION, MINIMO/VIP
    - Rules: underage validation, mandatory satellite tracker, visibility injuries, availability coverage
    """
    # Entity & Version
    entity = Entity(name="Test Policy", description="Test Desc")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED, changelog="V1"
    )
    db_session.add(version)
    db_session.commit()

    # Fields (Using the same as the real seed)
    f_nome = Field(entity_version_id=version.id, name="contraente_nome", label="Name", data_type=FieldType.STRING.value, is_free_value=True, is_required=True)
    f_nascita = Field(entity_version_id=version.id, name="contraente_nascita", label="Birthdate", data_type=FieldType.DATE.value, is_free_value=True, is_required=True)
    f_tipo = Field(entity_version_id=version.id, name="veicolo_tipo", label="Type", data_type=FieldType.STRING.value, is_free_value=False, is_required=True)
    f_valore = Field(entity_version_id=version.id, name="veicolo_valore", label="Value", data_type=FieldType.NUMBER.value, is_free_value=True, is_required=True)
    f_satellitare = Field(entity_version_id=version.id, name="veicolo_antifurto", label="Satellite Tracker", data_type=FieldType.BOOLEAN.value, is_free_value=True) # Default optional
    f_massimale = Field(entity_version_id=version.id, name="polizza_massimale", label="Coverage", data_type=FieldType.STRING.value, is_free_value=False, is_required=True)
    f_infortuni = Field(entity_version_id=version.id, name="polizza_infortuni", label="Injuries", data_type=FieldType.BOOLEAN.value, is_free_value=True)

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
    # 1. Underage Validation
    adult_date = date.today().replace(year=date.today().year - 18)
    r_underage = Rule(
        entity_version_id=version.id, target_field_id=f_nascita.id, rule_type=RuleType.VALIDATION.value,
        error_message="Underage",
        conditions={"criteria": [{"field_id": f_nascita.id, "operator": "GREATER_THAN", "value": str(adult_date)}]}
    )

    # 2. Mandatory Satellite Tracker if Value > 50000
    r_mand_sat = Rule(
        entity_version_id=version.id, target_field_id=f_satellitare.id, rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": f_valore.id, "operator": "GREATER_THAN", "value": 50000}]}
    )

    # 3. Visibility Injuries hidden if Moto
    r_hide_infortuni = Rule(
        entity_version_id=version.id, target_field_id=f_infortuni.id, rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": f_tipo.id, "operator": "NOT_EQUALS", "value": "MOTO"}]}
    )

    # 4. Availability No Minimum if Camion
    r_no_min_camion = Rule(
        entity_version_id=version.id, target_field_id=f_massimale.id, target_value_id=v_mass_min.id, rule_type=RuleType.AVAILABILITY.value,
        conditions={"criteria": [{"field_id": f_tipo.id, "operator": "NOT_EQUALS", "value": "CAMION"}]}
    )

    db_session.add_all([r_underage, r_mand_sat, r_hide_infortuni, r_no_min_camion])
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
    Scenario: Region -> City (cascading dropdowns).

    Region: [North, South]
    City: [Milano, Torino, Napoli, Palermo]

    Rules:
    - If Region == North -> Only Milano, Torino available
    - If Region == South -> Only Napoli, Palermo available
    """
    entity = Entity(name="Dropdown Test", description="Cascading menus")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # 1. Region Field (Dropdown)
    f_region = Field(entity_version_id=version.id, name="region", label="Region", data_type="string", sequence=1, is_free_value=False)
    db_session.add(f_region)
    db_session.commit()

    # Region values
    v_north = Value(field_id=f_region.id, value="NORD", label="North Italy")
    v_south = Value(field_id=f_region.id, value="SUD", label="South Italy")
    db_session.add_all([v_north, v_south])

    # 2. City Field (Dropdown)
    f_city = Field(entity_version_id=version.id, name="city", label="City", data_type="string", sequence=2, is_free_value=False)
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


# ============================================================
# SKU GENERATION FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def setup_sku_scenario(db_session):
    """
    Scenario for SKU generation testing.

    EntityVersion with sku_base="LPT-PRO", sku_delimiter="-"
    Fields:
    - CPU (step=1, seq=0): Intel i5 (I5), Intel i7 (I7), Intel i9 (I9)
    - RAM (step=1, seq=1): 16GB (16G), 32GB (32G)
    - GPU (step=2, seq=0): RTX 3060 (RTX3060), RTX 4080 (RTX4080)
    - Color (no sku_modifier): Black, White
    """
    entity = Entity(name="SKU Test Product", description="Testing SKU generation")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        sku_base="LPT-PRO",
        sku_delimiter="-"
    )
    db_session.add(version)
    db_session.commit()

    # Field: CPU (step=1, seq=0)
    f_cpu = Field(
        entity_version_id=version.id,
        name="cpu",
        label="CPU",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=False,
        step=1,
        sequence=0
    )
    # Field: RAM (step=1, seq=1)
    f_ram = Field(
        entity_version_id=version.id,
        name="ram",
        label="RAM",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=False,
        step=1,
        sequence=1
    )
    # Field: GPU (step=2, seq=0)
    f_gpu = Field(
        entity_version_id=version.id,
        name="gpu",
        label="GPU",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=False,
        step=2,
        sequence=0
    )
    # Field: Color (no sku_modifier on values)
    f_color = Field(
        entity_version_id=version.id,
        name="color",
        label="Color",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_required=False,
        step=3,
        sequence=0
    )
    # Field: Notes (free value)
    f_notes = Field(
        entity_version_id=version.id,
        name="notes",
        label="Notes",
        data_type=FieldType.STRING.value,
        is_free_value=True,
        is_required=False,
        step=4,
        sequence=0
    )

    db_session.add_all([f_cpu, f_ram, f_gpu, f_color, f_notes])
    db_session.commit()

    # CPU values with sku_modifier
    v_i5 = Value(field_id=f_cpu.id, value="Intel i5", label="Intel i5", sku_modifier="I5")
    v_i7 = Value(field_id=f_cpu.id, value="Intel i7", label="Intel i7", sku_modifier="I7")
    v_i9 = Value(field_id=f_cpu.id, value="Intel i9", label="Intel i9", sku_modifier="I9")

    # RAM values with sku_modifier
    v_16g = Value(field_id=f_ram.id, value="16GB", label="16GB", sku_modifier="16G")
    v_32g = Value(field_id=f_ram.id, value="32GB", label="32GB", sku_modifier="32G")

    # GPU values with sku_modifier
    v_rtx3060 = Value(field_id=f_gpu.id, value="RTX 3060", label="RTX 3060", sku_modifier="RTX3060")
    v_rtx4080 = Value(field_id=f_gpu.id, value="RTX 4080", label="RTX 4080", sku_modifier="RTX4080")

    # Color values WITHOUT sku_modifier
    v_black = Value(field_id=f_color.id, value="Black", label="Black", sku_modifier=None)
    v_white = Value(field_id=f_color.id, value="White", label="White", sku_modifier=None)

    db_session.add_all([v_i5, v_i7, v_i9, v_16g, v_32g, v_rtx3060, v_rtx4080, v_black, v_white])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {
            "cpu": f_cpu.id,
            "ram": f_ram.id,
            "gpu": f_gpu.id,
            "color": f_color.id,
            "notes": f_notes.id
        },
        "values": {
            "i5": v_i5.id,
            "i7": v_i7.id,
            "i9": v_i9.id,
            "16g": v_16g.id,
            "32g": v_32g.id,
            "rtx3060": v_rtx3060.id,
            "rtx4080": v_rtx4080.id,
            "black": v_black.id,
            "white": v_white.id
        }
    }


@pytest.fixture(scope="function")
def setup_sku_visibility_scenario(db_session):
    """
    Scenario for testing SKU with visibility rules.

    EntityVersion with sku_base="LPT"
    Fields:
    - Type: Desktop (DSK), Laptop (LPT)
    - CPU: Intel i7 (I7) - visible only if Type != Desktop
    - RAM: 32GB (32G)

    Rule: CPU hidden if Type == Desktop
    """
    entity = Entity(name="SKU Visibility Test", description="SKU with visibility rules")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        sku_base="LPT",
        sku_delimiter="-"
    )
    db_session.add(version)
    db_session.commit()

    # Field: Type
    f_type = Field(
        entity_version_id=version.id,
        name="type",
        label="Type",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        step=1,
        sequence=0
    )
    # Field: CPU (can be hidden by rule)
    f_cpu = Field(
        entity_version_id=version.id,
        name="cpu",
        label="CPU",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        step=2,
        sequence=0
    )
    # Field: RAM (always visible)
    f_ram = Field(
        entity_version_id=version.id,
        name="ram",
        label="RAM",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        step=3,
        sequence=0
    )

    db_session.add_all([f_type, f_cpu, f_ram])
    db_session.commit()

    # Type values
    v_desktop = Value(field_id=f_type.id, value="Desktop", label="Desktop", sku_modifier="DSK")
    v_laptop = Value(field_id=f_type.id, value="Laptop", label="Laptop", sku_modifier="LPT")

    # CPU values
    v_i7 = Value(field_id=f_cpu.id, value="Intel i7", label="Intel i7", sku_modifier="I7")

    # RAM values
    v_32g = Value(field_id=f_ram.id, value="32GB", label="32GB", sku_modifier="32G")

    db_session.add_all([v_desktop, v_laptop, v_i7, v_32g])
    db_session.commit()

    # Rule: CPU visible only if Type != Desktop (hidden when Desktop)
    rule_hide_cpu = Rule(
        entity_version_id=version.id,
        target_field_id=f_cpu.id,
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": f_type.id, "operator": "NOT_EQUALS", "value": "Desktop"}]}
    )
    db_session.add(rule_hide_cpu)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {
            "type": f_type.id,
            "cpu": f_cpu.id,
            "ram": f_ram.id
        },
        "values": {
            "desktop": v_desktop.id,
            "laptop": v_laptop.id,
            "i7": v_i7.id,
            "32g": v_32g.id
        }
    }


@pytest.fixture(scope="function")
def setup_sku_hidden_default_scenario(db_session):
    """
    Scenario for testing SKU with field hidden by default (is_hidden=True).

    EntityVersion with sku_base="LPT"
    Fields:
    - CPU: Intel i7 (I7) - hidden by default
    - RAM: 32GB (32G) - visible
    """
    entity = Entity(name="SKU Hidden Default", description="SKU with hidden field")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        sku_base="LPT",
        sku_delimiter="-"
    )
    db_session.add(version)
    db_session.commit()

    # Field: CPU (hidden by default)
    f_cpu = Field(
        entity_version_id=version.id,
        name="cpu",
        label="CPU",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_hidden=True,  # Hidden by default
        step=1,
        sequence=0
    )
    # Field: RAM (visible)
    f_ram = Field(
        entity_version_id=version.id,
        name="ram",
        label="RAM",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        is_hidden=False,
        step=2,
        sequence=0
    )

    db_session.add_all([f_cpu, f_ram])
    db_session.commit()

    v_i7 = Value(field_id=f_cpu.id, value="Intel i7", label="Intel i7", sku_modifier="I7")
    v_32g = Value(field_id=f_ram.id, value="32GB", label="32GB", sku_modifier="32G")

    db_session.add_all([v_i7, v_32g])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {
            "cpu": f_cpu.id,
            "ram": f_ram.id
        },
        "values": {
            "i7": v_i7.id,
            "32g": v_32g.id
        }
    }


@pytest.fixture(scope="function")
def setup_sku_availability_scenario(db_session):
    """
    Scenario for testing SKU with availability rules.

    EntityVersion with sku_base="LPT"
    Fields:
    - Type: Standard (STD), Premium (PRE)
    - RAM: 16GB (16G) - only for Standard, 32GB (32G) - always available

    Rule: 16GB available only if Type == Standard
    """
    entity = Entity(name="SKU Availability Test", description="SKU with availability rules")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        sku_base="LPT",
        sku_delimiter="-"
    )
    db_session.add(version)
    db_session.commit()

    # Field: Type
    f_type = Field(
        entity_version_id=version.id,
        name="type",
        label="Type",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        step=1,
        sequence=0
    )
    # Field: RAM
    f_ram = Field(
        entity_version_id=version.id,
        name="ram",
        label="RAM",
        data_type=FieldType.STRING.value,
        is_free_value=False,
        step=2,
        sequence=0
    )

    db_session.add_all([f_type, f_ram])
    db_session.commit()

    # Type values
    v_standard = Value(field_id=f_type.id, value="Standard", label="Standard", sku_modifier="STD")
    v_premium = Value(field_id=f_type.id, value="Premium", label="Premium", sku_modifier="PRE")

    # RAM values
    v_16g = Value(field_id=f_ram.id, value="16GB", label="16GB", sku_modifier="16G")
    v_32g = Value(field_id=f_ram.id, value="32GB", label="32GB", sku_modifier="32G")

    db_session.add_all([v_standard, v_premium, v_16g, v_32g])
    db_session.commit()

    # Rule: 16GB available only if Type == Standard
    rule_16g_availability = Rule(
        entity_version_id=version.id,
        target_field_id=f_ram.id,
        target_value_id=v_16g.id,
        rule_type=RuleType.AVAILABILITY.value,
        conditions={"criteria": [{"field_id": f_type.id, "operator": "EQUALS", "value": "Standard"}]}
    )
    db_session.add(rule_16g_availability)
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {
            "type": f_type.id,
            "ram": f_ram.id
        },
        "values": {
            "standard": v_standard.id,
            "premium": v_premium.id,
            "16g": v_16g.id,
            "32g": v_32g.id
        }
    }


# ============================================================
# CALCULATION FIXTURES
# ============================================================

@pytest.fixture(scope="function")
def setup_calculation_scenario(db_session):
    """
    Scenario for CALCULATION rule testing.

    EntityVersion with sku_base="CFG"
    Fields (ordered by step/sequence):
    - product_type (step=1): Standard, Pro, Enterprise (dropdown, required)
    - cooling_system (step=2): Passive (PAS), Active (ACT), Liquid (LIQ) (dropdown, required)
        CALCULATION: If product_type == "Enterprise", force "Passive"
    - support_tier (step=3): free-value field
        CALCULATION: If product_type == "Pro", force "Premium"
    - notes (step=4): free-value, optional
        EDITABILITY: readonly if product_type == "Standard"
    - warranty (step=5): 1 Year (1Y), 3 Years (3Y) (dropdown, required)
        AVAILABILITY: 3 Years only if product_type != "Standard"
        CALCULATION: If product_type == "Enterprise", force "3 Years"
    - status_display (step=6): free-value, required
        MANDATORY: required if product_type == "Pro"
        VISIBILITY: hidden if product_type == "Standard"
    """
    entity = Entity(name="Calculation Test", description="Testing CALCULATION rules")
    db_session.add(entity)
    db_session.commit()

    version = EntityVersion(
        entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED,
        sku_base="CFG", sku_delimiter="-"
    )
    db_session.add(version)
    db_session.commit()

    # Field 1: product_type (dropdown)
    f_product = Field(
        entity_version_id=version.id, name="product_type", label="Product Type",
        data_type=FieldType.STRING.value, is_free_value=False, is_required=True,
        step=1, sequence=0
    )
    # Field 2: cooling_system (dropdown, target of CALCULATION)
    f_cooling = Field(
        entity_version_id=version.id, name="cooling_system", label="Cooling System",
        data_type=FieldType.STRING.value, is_free_value=False, is_required=True,
        step=2, sequence=0
    )
    # Field 3: support_tier (free-value, target of CALCULATION)
    f_support = Field(
        entity_version_id=version.id, name="support_tier", label="Support Tier",
        data_type=FieldType.STRING.value, is_free_value=True, is_required=False,
        step=3, sequence=0
    )
    # Field 4: notes (free-value, target of EDITABILITY)
    f_notes = Field(
        entity_version_id=version.id, name="notes", label="Notes",
        data_type=FieldType.STRING.value, is_free_value=True, is_required=False,
        step=4, sequence=0
    )
    # Field 5: warranty (dropdown, target of CALCULATION + AVAILABILITY)
    f_warranty = Field(
        entity_version_id=version.id, name="warranty", label="Warranty",
        data_type=FieldType.STRING.value, is_free_value=False, is_required=True,
        step=5, sequence=0
    )
    # Field 6: status_display (free-value, target of VISIBILITY + MANDATORY)
    f_status = Field(
        entity_version_id=version.id, name="status_display", label="Status Display",
        data_type=FieldType.STRING.value, is_free_value=True, is_required=False,
        step=6, sequence=0
    )

    db_session.add_all([f_product, f_cooling, f_support, f_notes, f_warranty, f_status])
    db_session.commit()

    # Values: product_type
    v_standard = Value(field_id=f_product.id, value="Standard", label="Standard", sku_modifier="STD")
    v_pro = Value(field_id=f_product.id, value="Pro", label="Pro", sku_modifier="PRO")
    v_enterprise = Value(field_id=f_product.id, value="Enterprise", label="Enterprise", sku_modifier="ENT")

    # Values: cooling_system
    v_passive = Value(field_id=f_cooling.id, value="Passive", label="Passive", sku_modifier="PAS")
    v_active = Value(field_id=f_cooling.id, value="Active", label="Active", sku_modifier="ACT")
    v_liquid = Value(field_id=f_cooling.id, value="Liquid", label="Liquid", sku_modifier="LIQ")

    # Values: warranty
    v_1y = Value(field_id=f_warranty.id, value="1 Year", label="1 Year", sku_modifier="1Y")
    v_3y = Value(field_id=f_warranty.id, value="3 Years", label="3 Years", sku_modifier="3Y")

    db_session.add_all([v_standard, v_pro, v_enterprise, v_passive, v_active, v_liquid, v_1y, v_3y])
    db_session.commit()

    # CALCULATION: cooling_system = "Passive" if product_type == "Enterprise"
    r_calc_cooling = Rule(
        entity_version_id=version.id, target_field_id=f_cooling.id,
        rule_type=RuleType.CALCULATION.value,
        set_value="Passive",
        conditions={"criteria": [{"field_id": f_product.id, "operator": "EQUALS", "value": "Enterprise"}]}
    )

    # CALCULATION: support_tier = "Premium" if product_type == "Pro" (free-value field)
    r_calc_support = Rule(
        entity_version_id=version.id, target_field_id=f_support.id,
        rule_type=RuleType.CALCULATION.value,
        set_value="Premium",
        conditions={"criteria": [{"field_id": f_product.id, "operator": "EQUALS", "value": "Pro"}]}
    )

    # EDITABILITY: notes readonly if product_type == "Standard"
    r_edit_notes = Rule(
        entity_version_id=version.id, target_field_id=f_notes.id,
        rule_type=RuleType.EDITABILITY.value,
        conditions={"criteria": [{"field_id": f_product.id, "operator": "NOT_EQUALS", "value": "Standard"}]}
    )

    # AVAILABILITY: 3 Years only if product_type != "Standard"
    r_avail_3y = Rule(
        entity_version_id=version.id, target_field_id=f_warranty.id,
        target_value_id=v_3y.id,
        rule_type=RuleType.AVAILABILITY.value,
        conditions={"criteria": [{"field_id": f_product.id, "operator": "NOT_EQUALS", "value": "Standard"}]}
    )

    # CALCULATION: warranty = "3 Years" if product_type == "Enterprise"
    r_calc_warranty = Rule(
        entity_version_id=version.id, target_field_id=f_warranty.id,
        rule_type=RuleType.CALCULATION.value,
        set_value="3 Years",
        conditions={"criteria": [{"field_id": f_product.id, "operator": "EQUALS", "value": "Enterprise"}]}
    )

    # VISIBILITY: status_display hidden if product_type == "Standard"
    r_vis_status = Rule(
        entity_version_id=version.id, target_field_id=f_status.id,
        rule_type=RuleType.VISIBILITY.value,
        conditions={"criteria": [{"field_id": f_product.id, "operator": "NOT_EQUALS", "value": "Standard"}]}
    )

    # MANDATORY: status_display required if product_type == "Pro"
    r_mand_status = Rule(
        entity_version_id=version.id, target_field_id=f_status.id,
        rule_type=RuleType.MANDATORY.value,
        conditions={"criteria": [{"field_id": f_product.id, "operator": "EQUALS", "value": "Pro"}]}
    )

    db_session.add_all([
        r_calc_cooling, r_calc_support, r_edit_notes,
        r_avail_3y, r_calc_warranty, r_vis_status, r_mand_status
    ])
    db_session.commit()

    return {
        "entity_id": entity.id,
        "version_id": version.id,
        "fields": {
            "product_type": f_product.id,
            "cooling_system": f_cooling.id,
            "support_tier": f_support.id,
            "notes": f_notes.id,
            "warranty": f_warranty.id,
            "status_display": f_status.id,
        },
        "values": {
            "standard": v_standard.id,
            "pro": v_pro.id,
            "enterprise": v_enterprise.id,
            "passive": v_passive.id,
            "active": v_active.id,
            "liquid": v_liquid.id,
            "1y": v_1y.id,
            "3y": v_3y.id,
        }
    }
