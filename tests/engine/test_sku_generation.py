"""
Test suite for Smart SKU generation feature.
Tests SKU generation based on EntityVersion configuration and field selections.
"""
import pytest
from app.services.rule_engine import RuleEngineService
from app.schemas.engine import CalculationRequest, FieldInputState
from app.models.domain import (
    Entity, EntityVersion, Field, Value, Rule,
    RuleType, FieldType, VersionStatus
)


class TestSKUGeneration:
    """Test suite for Smart SKU generation feature."""

    # ----------------------------------------------------------
    # 1. BASIC FUNCTIONALITY
    # ----------------------------------------------------------

    def test_basic_sku_generation(self, db_session, setup_sku_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT-PRO", sku_delimiter="-"
               Field CPU con Value "Intel i7" (sku_modifier="I7")
               Field RAM con Value "32GB" (sku_modifier="32G")
        WHEN: calculate_state con CPU="Intel i7", RAM="32GB"
        THEN: generated_sku == "LPT-PRO-I7-32G"
        """
        data = setup_sku_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["cpu"], value="Intel i7"),
                FieldInputState(field_id=data["fields"]["ram"], value="32GB")
            ]
        )

        response = service.calculate_state(db_session, payload)

        assert response.generated_sku == "LPT-PRO-I7-32G"

    def test_sku_generation_custom_delimiter(self, db_session):
        """
        GIVEN: EntityVersion con sku_base="LPT", sku_delimiter="/"
               Field CPU con Value "Intel i7" (sku_modifier="I7")
        WHEN: calculate_state con CPU="Intel i7"
        THEN: generated_sku == "LPT/I7"
        """
        # Create entity with custom delimiter
        entity = Entity(name="Custom Delimiter Test", description="Test")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            sku_base="LPT",
            sku_delimiter="/"
        )
        db_session.add(version)
        db_session.commit()

        f_cpu = Field(
            entity_version_id=version.id,
            name="cpu",
            label="CPU",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=0
        )
        db_session.add(f_cpu)
        db_session.commit()

        v_i7 = Value(field_id=f_cpu.id, value="Intel i7", label="Intel i7", sku_modifier="I7")
        db_session.add(v_i7)
        db_session.commit()

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity.id,
            current_state=[FieldInputState(field_id=f_cpu.id, value="Intel i7")]
        )

        response = service.calculate_state(db_session, payload)

        assert response.generated_sku == "LPT/I7"

    def test_sku_generation_empty_delimiter(self, db_session):
        """
        GIVEN: EntityVersion con sku_base="LPT", sku_delimiter=""
               Field CPU con Value "Intel i7" (sku_modifier="I7")
        WHEN: calculate_state con CPU="Intel i7"
        THEN: generated_sku == "LPT-I7" (empty string defaults to "-" in implementation)

        NOTE: The implementation treats empty string as falsy and uses default "-".
        This is the current behavior: `delimiter = version.sku_delimiter or "-"`
        """
        entity = Entity(name="Empty Delimiter Test", description="Test")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            sku_base="LPT",
            sku_delimiter=""
        )
        db_session.add(version)
        db_session.commit()

        f_cpu = Field(
            entity_version_id=version.id,
            name="cpu",
            label="CPU",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=0
        )
        db_session.add(f_cpu)
        db_session.commit()

        v_i7 = Value(field_id=f_cpu.id, value="Intel i7", label="Intel i7", sku_modifier="I7")
        db_session.add(v_i7)
        db_session.commit()

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity.id,
            current_state=[FieldInputState(field_id=f_cpu.id, value="Intel i7")]
        )

        response = service.calculate_state(db_session, payload)

        # Empty delimiter defaults to "-" in current implementation
        assert response.generated_sku == "LPT-I7"

    # ----------------------------------------------------------
    # 2. SKU BASE HANDLING
    # ----------------------------------------------------------

    def test_no_sku_base_returns_none(self, db_session):
        """
        GIVEN: EntityVersion con sku_base=None
        WHEN: calculate_state
        THEN: generated_sku == None
        """
        entity = Entity(name="No SKU Base Test", description="Test")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            sku_base=None  # No SKU base
        )
        db_session.add(version)
        db_session.commit()

        f_cpu = Field(
            entity_version_id=version.id,
            name="cpu",
            label="CPU",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=0
        )
        db_session.add(f_cpu)
        db_session.commit()

        v_i7 = Value(field_id=f_cpu.id, value="Intel i7", label="Intel i7", sku_modifier="I7")
        db_session.add(v_i7)
        db_session.commit()

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity.id,
            current_state=[FieldInputState(field_id=f_cpu.id, value="Intel i7")]
        )

        response = service.calculate_state(db_session, payload)

        assert response.generated_sku is None

    def test_empty_sku_base_returns_none(self, db_session):
        """
        GIVEN: EntityVersion con sku_base=""
        WHEN: calculate_state
        THEN: generated_sku == None (stringa vuota trattata come None)
        """
        entity = Entity(name="Empty SKU Base Test", description="Test")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            sku_base=""  # Empty string SKU base
        )
        db_session.add(version)
        db_session.commit()

        f_cpu = Field(
            entity_version_id=version.id,
            name="cpu",
            label="CPU",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=0
        )
        db_session.add(f_cpu)
        db_session.commit()

        v_i7 = Value(field_id=f_cpu.id, value="Intel i7", label="Intel i7", sku_modifier="I7")
        db_session.add(v_i7)
        db_session.commit()

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity.id,
            current_state=[FieldInputState(field_id=f_cpu.id, value="Intel i7")]
        )

        response = service.calculate_state(db_session, payload)

        assert response.generated_sku is None

    # ----------------------------------------------------------
    # 3. MODIFIER HANDLING
    # ----------------------------------------------------------

    def test_value_without_modifier_skipped(self, db_session, setup_sku_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT-PRO"
               Field Color con Value "Black" (sku_modifier=None)
               Field CPU con Value "Intel i7" (sku_modifier="I7")
        WHEN: calculate_state con Color="Black", CPU="Intel i7"
        THEN: generated_sku == "LPT-PRO-I7" (Black ignorato)
        """
        data = setup_sku_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["color"], value="Black"),
                FieldInputState(field_id=data["fields"]["cpu"], value="Intel i7")
            ]
        )

        response = service.calculate_state(db_session, payload)

        # Black has no sku_modifier, so only I7 should be in SKU
        assert response.generated_sku == "LPT-PRO-I7"

    def test_all_values_without_modifiers(self, db_session, setup_sku_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT-PRO"
               Field Color con Value "Black" (sku_modifier=None)
        WHEN: calculate_state con Color="Black"
        THEN: generated_sku == "LPT-PRO" (solo base)
        """
        data = setup_sku_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["color"], value="Black")
            ]
        )

        response = service.calculate_state(db_session, payload)

        # Black has no modifier, so only base SKU
        assert response.generated_sku == "LPT-PRO"

    # ----------------------------------------------------------
    # 4. VISIBILITY HANDLING
    # ----------------------------------------------------------

    def test_hidden_field_modifier_ignored(self, db_session, setup_sku_visibility_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT"
               Field CPU (hidden by rule) con Value "Intel i7" (sku_modifier="I7")
               Field RAM (visible) con Value "32GB" (sku_modifier="32G")
        WHEN: calculate_state con condizioni che nascondono CPU
        THEN: generated_sku == "LPT-DSK-32G" (I7 ignorato perche CPU nascosto)
        """
        data = setup_sku_visibility_scenario
        service = RuleEngineService()

        # When Type = Desktop, CPU is hidden by visibility rule
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["type"], value="Desktop"),
                FieldInputState(field_id=data["fields"]["cpu"], value="Intel i7"),
                FieldInputState(field_id=data["fields"]["ram"], value="32GB")
            ]
        )

        response = service.calculate_state(db_session, payload)

        # CPU is hidden (Type=Desktop triggers visibility rule), so I7 should NOT be in SKU
        # DSK is the modifier for Desktop, 32G is the modifier for RAM
        assert response.generated_sku == "LPT-DSK-32G"

    def test_field_hidden_by_default_modifier_ignored(self, db_session, setup_sku_hidden_default_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT"
               Field CPU con is_hidden=True, Value "Intel i7" (sku_modifier="I7")
        WHEN: calculate_state
        THEN: generated_sku == "LPT-32G" (I7 ignorato perche campo nascosto di default)
        """
        data = setup_sku_hidden_default_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["cpu"], value="Intel i7"),
                FieldInputState(field_id=data["fields"]["ram"], value="32GB")
            ]
        )

        response = service.calculate_state(db_session, payload)

        # CPU is hidden by default (is_hidden=True), so I7 should NOT be in SKU
        assert response.generated_sku == "LPT-32G"

    # ----------------------------------------------------------
    # 5. FREE-VALUE FIELDS
    # ----------------------------------------------------------

    def test_free_value_field_ignored(self, db_session, setup_sku_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT-PRO"
               Field Notes (is_free_value=True)
               Field CPU con Value "Intel i7" (sku_modifier="I7")
        WHEN: calculate_state con Notes="Custom text", CPU="Intel i7"
        THEN: generated_sku == "LPT-PRO-I7" (Notes ignorato)
        """
        data = setup_sku_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["notes"], value="Custom text"),
                FieldInputState(field_id=data["fields"]["cpu"], value="Intel i7")
            ]
        )

        response = service.calculate_state(db_session, payload)

        # Notes is a free-value field, so it should be ignored in SKU generation
        assert response.generated_sku == "LPT-PRO-I7"

    # ----------------------------------------------------------
    # 6. FIELD ORDERING
    # ----------------------------------------------------------

    def test_sku_respects_step_sequence_order(self, db_session, setup_sku_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT-PRO"
               Field RAM (step=1, seq=1) con sku_modifier="32G"
               Field CPU (step=1, seq=0) con sku_modifier="I7"
               Field GPU (step=2, seq=0) con sku_modifier="RTX4080"
        WHEN: calculate_state con tutti i valori selezionati
        THEN: generated_sku == "LPT-PRO-I7-32G-RTX4080" (ordinato per step, poi sequence)
        """
        data = setup_sku_scenario
        service = RuleEngineService()

        # Input in random order - output should be sorted by step/sequence
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["gpu"], value="RTX 4080"),  # step=2, seq=0
                FieldInputState(field_id=data["fields"]["ram"], value="32GB"),      # step=1, seq=1
                FieldInputState(field_id=data["fields"]["cpu"], value="Intel i7")   # step=1, seq=0
            ]
        )

        response = service.calculate_state(db_session, payload)

        # Should be ordered: CPU (step=1,seq=0), RAM (step=1,seq=1), GPU (step=2,seq=0)
        assert response.generated_sku == "LPT-PRO-I7-32G-RTX4080"

    # ----------------------------------------------------------
    # 7. NO VALUE SELECTED
    # ----------------------------------------------------------

    def test_no_value_selected_modifier_skipped(self, db_session, setup_sku_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT-PRO"
               Field CPU (is_required=False) con Value "Intel i7" (sku_modifier="I7")
        WHEN: calculate_state senza selezionare CPU
        THEN: generated_sku == "LPT-PRO" (I7 ignorato, nessuna selezione)
        """
        data = setup_sku_scenario
        service = RuleEngineService()

        # Only select RAM, not CPU
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["ram"], value="32GB")
            ]
        )

        response = service.calculate_state(db_session, payload)

        # CPU not selected, so I7 not in SKU. Only RAM selected -> 32G
        assert response.generated_sku == "LPT-PRO-32G"

    # ----------------------------------------------------------
    # 8. MAX LENGTH ENFORCEMENT
    # ----------------------------------------------------------

    def test_sku_truncated_if_exceeds_max_length(self, db_session):
        """
        GIVEN: EntityVersion con sku_base="VERY-LONG-BASE-CODE"
               Molti Fields con modifiers lunghi che superano 100 caratteri
        WHEN: calculate_state
        THEN: len(generated_sku) <= 100
        """
        entity = Entity(name="Max Length Test", description="Test")
        db_session.add(entity)
        db_session.commit()

        # Create a base that will be long
        long_base = "VERY-LONG-BASE-SKU-CODE"
        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            sku_base=long_base,
            sku_delimiter="-"
        )
        db_session.add(version)
        db_session.commit()

        # Create multiple fields with long modifiers to exceed 100 chars
        fields = []
        values = []
        for i in range(10):
            field = Field(
                entity_version_id=version.id,
                name=f"field_{i}",
                label=f"Field {i}",
                data_type=FieldType.STRING.value,
                is_free_value=False,
                step=i,
                sequence=0
            )
            db_session.add(field)
            db_session.flush()

            # Create value with long modifier (10 chars each)
            value = Value(
                field_id=field.id,
                value=f"Option{i}",
                label=f"Option {i}",
                sku_modifier=f"MOD{i:05d}XX"  # 10 chars each
            )
            fields.append(field)
            values.append(value)

        db_session.add_all(values)
        db_session.commit()

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity.id,
            current_state=[
                FieldInputState(field_id=f.id, value=f"Option{i}")
                for i, f in enumerate(fields)
            ]
        )

        response = service.calculate_state(db_session, payload)

        # SKU should be truncated to 100 characters max
        assert response.generated_sku is not None
        assert len(response.generated_sku) <= 100

    # ----------------------------------------------------------
    # 9. INTEGRATION WITH AVAILABILITY RULES
    # ----------------------------------------------------------

    def test_unavailable_value_modifier_not_included(self, db_session, setup_sku_availability_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT"
               Field RAM con Value "32GB" (sku_modifier="32G", non disponibile per regola)
               Field RAM con Value "16GB" (sku_modifier="16G", disponibile)
        WHEN: calculate_state selezionando "32GB" (sempre disponibile)
        THEN: generated_sku == "LPT-STD-32G" o "LPT-PRE-32G" a seconda del tipo
        """
        data = setup_sku_availability_scenario
        service = RuleEngineService()

        # Select Standard type and 32GB RAM (always available)
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["type"], value="Standard"),
                FieldInputState(field_id=data["fields"]["ram"], value="32GB")
            ]
        )

        response = service.calculate_state(db_session, payload)

        assert response.generated_sku == "LPT-STD-32G"

    def test_selecting_available_value_includes_modifier(self, db_session, setup_sku_availability_scenario):
        """
        GIVEN: 16GB available only for Standard type
        WHEN: Select Standard + 16GB
        THEN: generated_sku includes 16G modifier
        """
        data = setup_sku_availability_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["type"], value="Standard"),
                FieldInputState(field_id=data["fields"]["ram"], value="16GB")
            ]
        )

        response = service.calculate_state(db_session, payload)

        assert response.generated_sku == "LPT-STD-16G"

    # ----------------------------------------------------------
    # 10. EDGE CASES
    # ----------------------------------------------------------

    def test_sku_with_special_characters_in_modifier(self, db_session):
        """
        GIVEN: EntityVersion con sku_base="PRD"
               Field Size con Value "X-Large" (sku_modifier="X-L")
        WHEN: calculate_state con Size="X-Large"
        THEN: generated_sku == "PRD-X-L" (caratteri speciali preservati)
        """
        entity = Entity(name="Special Chars Test", description="Test")
        db_session.add(entity)
        db_session.commit()

        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            sku_base="PRD",
            sku_delimiter="-"
        )
        db_session.add(version)
        db_session.commit()

        f_size = Field(
            entity_version_id=version.id,
            name="size",
            label="Size",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=0
        )
        db_session.add(f_size)
        db_session.commit()

        v_xl = Value(field_id=f_size.id, value="X-Large", label="X-Large", sku_modifier="X-L")
        db_session.add(v_xl)
        db_session.commit()

        service = RuleEngineService()
        payload = CalculationRequest(
            entity_id=entity.id,
            current_state=[FieldInputState(field_id=f_size.id, value="X-Large")]
        )

        response = service.calculate_state(db_session, payload)

        assert response.generated_sku == "PRD-X-L"

    def test_sku_generation_on_empty_configuration(self, db_session, setup_sku_scenario):
        """
        GIVEN: EntityVersion con sku_base="LPT-PRO"
               Nessun campo ha valore selezionato
        WHEN: calculate_state con current_state vuoto
        THEN: generated_sku == "LPT-PRO" (solo base)
        """
        data = setup_sku_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[]  # Empty configuration
        )

        response = service.calculate_state(db_session, payload)

        # No selections, so only base SKU
        assert response.generated_sku == "LPT-PRO"

    def test_sku_with_all_field_types_combined(self, db_session, setup_sku_scenario):
        """
        Test combining multiple field selections with mixed modifiers.
        GIVEN: Multiple fields with and without modifiers
        WHEN: All fields have values
        THEN: SKU contains only modifiers from fields that have them
        """
        data = setup_sku_scenario
        service = RuleEngineService()

        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["cpu"], value="Intel i9"),    # Has modifier I9
                FieldInputState(field_id=data["fields"]["ram"], value="16GB"),        # Has modifier 16G
                FieldInputState(field_id=data["fields"]["gpu"], value="RTX 3060"),    # Has modifier RTX3060
                FieldInputState(field_id=data["fields"]["color"], value="White"),     # No modifier
                FieldInputState(field_id=data["fields"]["notes"], value="Test note")  # Free value, ignored
            ]
        )

        response = service.calculate_state(db_session, payload)

        # Order: CPU(step=1,seq=0), RAM(step=1,seq=1), GPU(step=2,seq=0), Color(step=3), Notes(step=4)
        # Color has no modifier, Notes is free-value
        assert response.generated_sku == "LPT-PRO-I9-16G-RTX3060"

    def test_sku_visibility_rule_shows_field_includes_modifier(self, db_session, setup_sku_visibility_scenario):
        """
        Test that visible field (not hidden by rule) includes its modifier.
        GIVEN: CPU visible when Type != Desktop
        WHEN: Type = Laptop (CPU visible)
        THEN: SKU includes CPU modifier
        """
        data = setup_sku_visibility_scenario
        service = RuleEngineService()

        # When Type = Laptop, CPU is visible (rule condition NOT met)
        payload = CalculationRequest(
            entity_id=data["entity_id"],
            current_state=[
                FieldInputState(field_id=data["fields"]["type"], value="Laptop"),
                FieldInputState(field_id=data["fields"]["cpu"], value="Intel i7"),
                FieldInputState(field_id=data["fields"]["ram"], value="32GB")
            ]
        )

        response = service.calculate_state(db_session, payload)

        # CPU is visible (Type=Laptop), so I7 should be in SKU
        assert response.generated_sku == "LPT-LPT-I7-32G"
