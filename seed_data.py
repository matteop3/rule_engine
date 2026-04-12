import os
import sys
from datetime import date

# Fix path to import app modules from root
sys.path.append(os.getcwd())

from app.core.security import get_password_hash
from app.database import Base, SessionLocal, engine
from app.models.domain import (
    BOMItem,
    BOMItemRule,
    BOMType,
    Configuration,
    ConfigurationStatus,
    Entity,
    EntityVersion,
    Field,
    FieldType,
    PriceList,
    PriceListItem,
    RefreshToken,
    Rule,
    RuleType,
    User,
    UserRole,
    Value,
    VersionStatus,
)


def seed_db():
    db = SessionLocal()
    try:
        print("=" * 70)
        print("SEED DATA - Auto Insurance Gold (Full Demo with Cascading Rules)")
        print("=" * 70)

        # 1. Cleanup (order: FK dependencies)
        db.query(RefreshToken).delete()
        db.query(Configuration).delete()
        db.query(BOMItemRule).delete()
        db.query(BOMItem).delete()
        db.query(Rule).delete()
        db.query(Value).delete()
        db.query(Field).delete()
        db.query(EntityVersion).delete()
        db.query(Entity).delete()
        db.query(PriceListItem).delete()
        db.query(PriceList).delete()
        db.query(User).delete()
        db.commit()
        print("\n[1/10] Database cleaned.")

        # 2. Entity
        entity = Entity(
            name="Auto Insurance Gold",
            description="Full-featured auto insurance quote configurator with cascading rules",
        )
        db.add(entity)
        db.commit()
        print(f"[2/9] Entity created: {entity.name} (ID: {entity.id})")

        # 3. Version (with SKU configuration)
        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Full version with cascading rules and SKU generation",
            sku_base="POL-AUTO",
            sku_delimiter="-",
        )
        db.add(version)
        db.commit()
        print(f"[3/9] Version created: v{version.version_number} (SKU: {version.sku_base})")

        # ============================================================
        # 4. FIELDS (15 fields in 4 steps)
        # ============================================================

        # --- STEP 1: Policyholder Data ---
        f_name = Field(
            entity_version_id=version.id,
            name="policyholder_name",
            label="Full Name",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1,
            sequence=10,
            is_required=True,
        )

        f_dob = Field(
            entity_version_id=version.id,
            name="policyholder_dob",
            label="Date of Birth",
            data_type=FieldType.DATE.value,
            is_free_value=True,
            step=1,
            sequence=20,
            is_required=True,
        )

        f_occupation = Field(
            entity_version_id=version.id,
            name="policyholder_occupation",
            label="Occupation",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1,
            sequence=30,
            is_required=True,
        )

        # --- STEP 2: Vehicle Data ---
        f_vehicle_type = Field(
            entity_version_id=version.id,
            name="vehicle_type",
            label="Vehicle Type",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=2,
            sequence=10,
            is_required=True,
        )

        f_vehicle_value = Field(
            entity_version_id=version.id,
            name="vehicle_value",
            label="Vehicle Value ($)",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            step=2,
            sequence=20,
            is_required=True,
        )

        f_satellite_tracker = Field(
            entity_version_id=version.id,
            name="vehicle_satellite_tracker",
            label="Satellite Anti-Theft?",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True,
            step=2,
            sequence=30,
        )

        # --- CASCADING CHAIN 1: Truck → Cargo Type → ADR Certification ---
        # These fields are only visible when vehicle type = TRUCK
        f_cargo_type = Field(
            entity_version_id=version.id,
            name="truck_cargo_type",
            label="Cargo Type",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_hidden=True,  # Hidden by default, visible only for TRUCK
            step=2,
            sequence=40,
            is_required=False,  # Becomes required dynamically
        )

        f_adr_certification = Field(
            entity_version_id=version.id,
            name="truck_adr_certification",
            label="ADR Certification",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_hidden=True,  # Hidden by default, visible only for hazardous goods
            step=2,
            sequence=50,
            is_required=False,  # Becomes required dynamically
        )

        # --- STEP 3: Coverage ---
        f_premium_tier = Field(
            entity_version_id=version.id,
            name="policy_premium_tier",
            label="Estimated Premium Tier",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_readonly=True,  # Always readonly: value is calculated by the engine
            step=3,
            sequence=5,
        )

        f_liability_limit = Field(
            entity_version_id=version.id,
            name="policy_liability_limit",
            label="Liability Limit",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=3,
            sequence=10,
            is_required=True,
        )

        f_injury_coverage = Field(
            entity_version_id=version.id,
            name="policy_injury_coverage",
            label="Personal Injury Coverage",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=3,
            sequence=20,
        )

        f_theft_coverage = Field(
            entity_version_id=version.id,
            name="policy_theft_coverage",
            label="Theft & Fire Coverage",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=3,
            sequence=30,
        )

        # --- STEP 4: Additional Services (CASCADING CHAIN 2) ---
        # Roadside Assistance → Rental Car (visible only with premium assistance)
        f_roadside = Field(
            entity_version_id=version.id,
            name="services_roadside",
            label="Roadside Assistance",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=4,
            sequence=10,
        )

        f_rental_car = Field(
            entity_version_id=version.id,
            name="services_rental_car",
            label="Rental Car",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_hidden=True,  # Visible only with PREMIUM assistance
            step=4,
            sequence=20,
        )

        f_notes = Field(
            entity_version_id=version.id,
            name="additional_notes",
            label="Additional Notes",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            is_readonly=True,  # Readonly by default, editable only for some occupations
            default_value="No notes",
            step=4,
            sequence=30,
        )

        all_fields = [
            f_name,
            f_dob,
            f_occupation,
            f_vehicle_type,
            f_vehicle_value,
            f_satellite_tracker,
            f_cargo_type,
            f_adr_certification,
            f_premium_tier,
            f_liability_limit,
            f_injury_coverage,
            f_theft_coverage,
            f_roadside,
            f_rental_car,
            f_notes,
        ]
        db.add_all(all_fields)
        db.commit()
        print(f"[4/9] Fields created: {len(all_fields)} fields in 4 steps")

        # ============================================================
        # 5. VALUES (with SKU modifiers)
        # ============================================================

        # --- Occupation ---
        v_occ_employee = Value(
            field_id=f_occupation.id, label="Employee", value="EMPLOYEE", is_default=True, sku_modifier=None
        )
        v_occ_self = Value(field_id=f_occupation.id, label="Self-Employed", value="SELF_EMPLOYED", sku_modifier=None)
        v_occ_retired = Value(
            field_id=f_occupation.id, label="Retired", value="RETIRED", sku_modifier="P"
        )  # Retiree discount marker
        v_occ_student = Value(
            field_id=f_occupation.id, label="Student", value="STUDENT", sku_modifier="S"
        )  # Student discount marker

        # --- Vehicle Type ---
        v_car = Value(field_id=f_vehicle_type.id, label="Car", value="CAR", is_default=True, sku_modifier="A")
        v_motorcycle = Value(field_id=f_vehicle_type.id, label="Motorcycle", value="MOTORCYCLE", sku_modifier="M")
        v_truck = Value(field_id=f_vehicle_type.id, label="Truck", value="TRUCK", sku_modifier="C")
        v_van = Value(field_id=f_vehicle_type.id, label="Van", value="VAN", sku_modifier="F")

        # --- Cargo Type (only for TRUCK) ---
        v_cargo_standard = Value(
            field_id=f_cargo_type.id, label="Standard Goods", value="STANDARD", is_default=True, sku_modifier="TN"
        )
        v_cargo_refrigerated = Value(
            field_id=f_cargo_type.id, label="Refrigerated Goods", value="REFRIGERATED", sku_modifier="TR"
        )
        v_cargo_hazardous = Value(
            field_id=f_cargo_type.id, label="Hazardous Goods (ADR)", value="HAZARDOUS", sku_modifier="TP"
        )

        # --- ADR Certification (only for hazardous goods) ---
        v_adr_base = Value(
            field_id=f_adr_certification.id, label="ADR Basic", value="ADR_BASIC", is_default=True, sku_modifier="ADR1"
        )
        v_adr_tanks = Value(field_id=f_adr_certification.id, label="ADR Tanks", value="ADR_TANKS", sku_modifier="ADR2")
        v_adr_explosives = Value(
            field_id=f_adr_certification.id,
            label="ADR Explosives (Class 1)",
            value="ADR_EXPLOSIVES",
            sku_modifier="ADR3",
        )

        # --- Liability Limit ---
        v_limit_min = Value(
            field_id=f_liability_limit.id,
            label="Legal Minimum (6M)",
            value="MINIMUM",
            is_default=True,
            sku_modifier="6M",
        )
        v_limit_std = Value(field_id=f_liability_limit.id, label="Standard (10M)", value="STANDARD", sku_modifier="10M")
        v_limit_high = Value(field_id=f_liability_limit.id, label="High (25M)", value="HIGH", sku_modifier="25M")
        v_limit_vip = Value(field_id=f_liability_limit.id, label="Premium (50M)", value="VIP", sku_modifier="50M")

        # --- Personal Injury Coverage ---
        v_injury_none = Value(
            field_id=f_injury_coverage.id, label="Not Included", value="NO", is_default=True, sku_modifier=None
        )
        v_injury_basic = Value(field_id=f_injury_coverage.id, label="Basic (50k)", value="BASIC", sku_modifier="INF1")
        v_injury_full = Value(field_id=f_injury_coverage.id, label="Full (100k)", value="FULL", sku_modifier="INF2")

        # --- Theft & Fire Coverage ---
        v_theft_none = Value(
            field_id=f_theft_coverage.id, label="Not Included", value="NO", is_default=True, sku_modifier=None
        )
        v_theft_fire = Value(field_id=f_theft_coverage.id, label="Fire Only", value="FIRE", sku_modifier="INC")
        v_theft_full = Value(field_id=f_theft_coverage.id, label="Theft + Fire", value="FULL", sku_modifier="FI")

        # --- Roadside Assistance ---
        v_road_none = Value(
            field_id=f_roadside.id, label="Not Included", value="NO", is_default=True, sku_modifier=None
        )
        v_road_basic = Value(field_id=f_roadside.id, label="Basic (tow only)", value="BASIC", sku_modifier="AS1")
        v_road_plus = Value(field_id=f_roadside.id, label="Plus (tow + taxi)", value="PLUS", sku_modifier="AS2")
        v_road_premium = Value(
            field_id=f_roadside.id, label="Premium (all inclusive)", value="PREMIUM", sku_modifier="AS3"
        )

        # --- Rental Car (only with PREMIUM assistance) ---
        v_rental_none = Value(
            field_id=f_rental_car.id, label="Not Included", value="NO", is_default=True, sku_modifier=None
        )
        v_rental_3d = Value(field_id=f_rental_car.id, label="3 days", value="3D", sku_modifier="R3")
        v_rental_7d = Value(field_id=f_rental_car.id, label="7 days", value="7D", sku_modifier="R7")
        v_rental_15d = Value(field_id=f_rental_car.id, label="15 days", value="15D", sku_modifier="R15")

        # --- Premium Tier (calculated by engine) ---
        v_tier_economy = Value(field_id=f_premium_tier.id, label="Economy", value="ECONOMY", sku_modifier="EC")
        v_tier_standard = Value(field_id=f_premium_tier.id, label="Standard", value="STANDARD", sku_modifier="ST")
        v_tier_premium = Value(field_id=f_premium_tier.id, label="Premium", value="PREMIUM", sku_modifier="PR")

        all_values = [
            v_occ_employee,
            v_occ_self,
            v_occ_retired,
            v_occ_student,
            v_car,
            v_motorcycle,
            v_truck,
            v_van,
            v_cargo_standard,
            v_cargo_refrigerated,
            v_cargo_hazardous,
            v_adr_base,
            v_adr_tanks,
            v_adr_explosives,
            v_limit_min,
            v_limit_std,
            v_limit_high,
            v_limit_vip,
            v_injury_none,
            v_injury_basic,
            v_injury_full,
            v_theft_none,
            v_theft_fire,
            v_theft_full,
            v_road_none,
            v_road_basic,
            v_road_plus,
            v_road_premium,
            v_rental_none,
            v_rental_3d,
            v_rental_7d,
            v_rental_15d,
            v_tier_economy,
            v_tier_standard,
            v_tier_premium,
        ]
        db.add_all(all_values)
        db.commit()
        print(f"[5/9] Values created: {len(all_values)} values with SKU modifiers")

        # ============================================================
        # 6. RULES (19 rules: 6/6 types, 7/7 operators, 2 cascading chains)
        # ============================================================

        # --- VALIDATION: Must be 18+ ---
        today = date.today()
        min_adult_date = today.replace(year=today.year - 18)

        r_age_check = Rule(
            entity_version_id=version.id,
            target_field_id=f_dob.id,
            rule_type=RuleType.VALIDATION.value,
            description="Policyholder must be at least 18 years old",
            error_message="The policyholder must be at least 18 years old.",
            conditions={"criteria": [{"field_id": f_dob.id, "operator": "GREATER_THAN", "value": str(min_adult_date)}]},
        )

        # --- VALIDATION: Minimum vehicle value ---
        r_min_value = Rule(
            entity_version_id=version.id,
            target_field_id=f_vehicle_value.id,
            rule_type=RuleType.VALIDATION.value,
            description="Minimum vehicle value is $1,000",
            error_message="Vehicle value must be at least $1,000.",
            conditions={"criteria": [{"field_id": f_vehicle_value.id, "operator": "LESS_THAN", "value": 1000}]},
        )

        # --- VALIDATION: Max value for students ---
        r_student_max_value = Rule(
            entity_version_id=version.id,
            target_field_id=f_vehicle_value.id,
            rule_type=RuleType.VALIDATION.value,
            description="Students: max insurable value is $30,000",
            error_message="Students cannot insure vehicles worth more than $30,000.",
            conditions={
                "criteria": [
                    {"field_id": f_occupation.id, "operator": "EQUALS", "value": "STUDENT"},
                    {"field_id": f_vehicle_value.id, "operator": "GREATER_THAN", "value": 30000},
                ]
            },
        )

        # --- MANDATORY: Satellite tracker required for vehicles > 50k ---
        r_mand_tracker = Rule(
            entity_version_id=version.id,
            target_field_id=f_satellite_tracker.id,
            rule_type=RuleType.MANDATORY.value,
            description="Satellite tracker required for luxury vehicles",
            conditions={"criteria": [{"field_id": f_vehicle_value.id, "operator": "GREATER_THAN", "value": 50000}]},
        )

        # --- EDITABILITY: Satellite tracker readonly with VIP (included in package) ---
        r_readonly_tracker_vip = Rule(
            entity_version_id=version.id,
            target_field_id=f_satellite_tracker.id,
            rule_type=RuleType.EDITABILITY.value,
            description="Satellite tracker included in Premium package",
            conditions={"criteria": [{"field_id": f_liability_limit.id, "operator": "NOT_EQUALS", "value": "VIP"}]},
        )

        # ============================================================
        # CALCULATION: Premium Tier (engine-derived value)
        # ============================================================
        # The premium_tier field is always readonly. The engine evaluates
        # CALCULATION rules in order: first passing rule wins.

        r_calc_economy = Rule(
            entity_version_id=version.id,
            target_field_id=f_premium_tier.id,
            rule_type=RuleType.CALCULATION.value,
            description="ECONOMY tier for vehicles up to $15k",
            set_value="ECONOMY",
            conditions={
                "criteria": [{"field_id": f_vehicle_value.id, "operator": "LESS_THAN_OR_EQUAL", "value": 15000}]
            },
        )

        r_calc_standard = Rule(
            entity_version_id=version.id,
            target_field_id=f_premium_tier.id,
            rule_type=RuleType.CALCULATION.value,
            description="STANDARD tier for vehicles $15k-$50k",
            set_value="STANDARD",
            conditions={
                "criteria": [
                    {"field_id": f_vehicle_value.id, "operator": "GREATER_THAN", "value": 15000},
                    {"field_id": f_vehicle_value.id, "operator": "LESS_THAN_OR_EQUAL", "value": 50000},
                ]
            },
        )

        r_calc_premium = Rule(
            entity_version_id=version.id,
            target_field_id=f_premium_tier.id,
            rule_type=RuleType.CALCULATION.value,
            description="PREMIUM tier for vehicles over $50k",
            set_value="PREMIUM",
            conditions={"criteria": [{"field_id": f_vehicle_value.id, "operator": "GREATER_THAN", "value": 50000}]},
        )

        # ============================================================
        # EDITABILITY: Additional Notes (editable only for some occupations)
        # ============================================================
        # The field is readonly by default. This rule unlocks it
        # only for employees and self-employed (IN operator).

        r_edit_notes = Rule(
            entity_version_id=version.id,
            target_field_id=f_notes.id,
            rule_type=RuleType.EDITABILITY.value,
            description="Notes editable only for employees and self-employed",
            conditions={
                "criteria": [{"field_id": f_occupation.id, "operator": "IN", "value": ["EMPLOYEE", "SELF_EMPLOYED"]}]
            },
        )

        # ============================================================
        # CASCADING CHAIN 1: Truck → Cargo Type → ADR Certification
        # ============================================================

        # STEP 1: Show "Cargo Type" only if vehicle = TRUCK
        r_show_cargo_type = Rule(
            entity_version_id=version.id,
            target_field_id=f_cargo_type.id,
            rule_type=RuleType.VISIBILITY.value,
            description="[CHAIN 1.1] Cargo type visible only for Trucks",
            conditions={"criteria": [{"field_id": f_vehicle_type.id, "operator": "EQUALS", "value": "TRUCK"}]},
        )

        # STEP 1b: Cargo Type becomes required for TRUCK
        r_mand_cargo_type = Rule(
            entity_version_id=version.id,
            target_field_id=f_cargo_type.id,
            rule_type=RuleType.MANDATORY.value,
            description="[CHAIN 1.1b] Cargo type required for Trucks",
            conditions={"criteria": [{"field_id": f_vehicle_type.id, "operator": "EQUALS", "value": "TRUCK"}]},
        )

        # STEP 2: Show "ADR Certification" only if cargo = HAZARDOUS
        # This rule depends on the previous field (cargo_type) already processed
        r_show_adr = Rule(
            entity_version_id=version.id,
            target_field_id=f_adr_certification.id,
            rule_type=RuleType.VISIBILITY.value,
            description="[CHAIN 1.2] ADR visible only for hazardous goods",
            conditions={"criteria": [{"field_id": f_cargo_type.id, "operator": "EQUALS", "value": "HAZARDOUS"}]},
        )

        # STEP 2b: ADR Certification required for hazardous goods
        r_mand_adr = Rule(
            entity_version_id=version.id,
            target_field_id=f_adr_certification.id,
            rule_type=RuleType.MANDATORY.value,
            description="[CHAIN 1.2b] ADR required for hazardous goods",
            conditions={"criteria": [{"field_id": f_cargo_type.id, "operator": "EQUALS", "value": "HAZARDOUS"}]},
        )

        # ============================================================
        # CASCADING CHAIN 2: Premium Assistance → Rental Car
        # ============================================================

        # Show "Rental Car" only if assistance = PREMIUM
        r_show_rental = Rule(
            entity_version_id=version.id,
            target_field_id=f_rental_car.id,
            rule_type=RuleType.VISIBILITY.value,
            description="[CHAIN 2.1] Rental car only with Premium assistance",
            conditions={"criteria": [{"field_id": f_roadside.id, "operator": "EQUALS", "value": "PREMIUM"}]},
        )

        # ============================================================
        # AVAILABILITY RULES
        # ============================================================

        # No minimum liability limit for Trucks (commercial vehicles)
        r_no_min_limit_truck = Rule(
            entity_version_id=version.id,
            target_field_id=f_liability_limit.id,
            target_value_id=v_limit_min.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="No minimum liability limit for trucks",
            conditions={"criteria": [{"field_id": f_vehicle_type.id, "operator": "NOT_EQUALS", "value": "TRUCK"}]},
        )

        # No full theft coverage for Motorcycles (statistically unfavorable)
        r_no_theft_motorcycle = Rule(
            entity_version_id=version.id,
            target_field_id=f_theft_coverage.id,
            target_value_id=v_theft_full.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="Full theft coverage not available for motorcycles",
            conditions={"criteria": [{"field_id": f_vehicle_type.id, "operator": "NOT_EQUALS", "value": "MOTORCYCLE"}]},
        )

        # No injury coverage for Motorcycles
        r_hide_injury_motorcycle = Rule(
            entity_version_id=version.id,
            target_field_id=f_injury_coverage.id,
            rule_type=RuleType.VISIBILITY.value,
            description="No injury coverage for Motorcycles",
            conditions={"criteria": [{"field_id": f_vehicle_type.id, "operator": "NOT_EQUALS", "value": "MOTORCYCLE"}]},
        )

        # Full injury coverage only for Cars and Vans (IN operator)
        r_injury_full_car_van = Rule(
            entity_version_id=version.id,
            target_field_id=f_injury_coverage.id,
            target_value_id=v_injury_full.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="Full injury coverage only for cars and vans",
            conditions={"criteria": [{"field_id": f_vehicle_type.id, "operator": "IN", "value": ["CAR", "VAN"]}]},
        )

        # Rental car 15 days only for vehicles >= 40k
        r_rental_15d_luxury = Rule(
            entity_version_id=version.id,
            target_field_id=f_rental_car.id,
            target_value_id=v_rental_15d.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="15-day rental car only for luxury vehicles",
            conditions={
                "criteria": [{"field_id": f_vehicle_value.id, "operator": "GREATER_THAN_OR_EQUAL", "value": 40000}]
            },
        )

        all_rules = [
            # Validation
            r_age_check,
            r_min_value,
            r_student_max_value,
            # Calculation (premium tier derived from vehicle value)
            r_calc_economy,
            r_calc_standard,
            r_calc_premium,
            # Mandatory & Editability
            r_mand_tracker,
            r_readonly_tracker_vip,
            r_edit_notes,
            # Cascading Chain 1: Truck → Cargo → ADR
            r_show_cargo_type,
            r_mand_cargo_type,
            r_show_adr,
            r_mand_adr,
            # Cascading Chain 2: Assistance → Rental Car
            r_show_rental,
            # Availability
            r_no_min_limit_truck,
            r_no_theft_motorcycle,
            r_hide_injury_motorcycle,
            r_injury_full_car_van,
            r_rental_15d_luxury,
        ]
        db.add_all(all_rules)
        db.commit()
        print(f"[6/10] Rules created: {len(all_rules)} rules (6/6 types + 2 cascading chains)")

        # ============================================================
        # 7. BOM ITEMS AND RULES
        # ============================================================
        # The insurance entity doubles as a demonstration of BOM generation.
        # TECHNICAL items represent underwriting components; COMMERCIAL items
        # represent priced line items on the quote.

        # --- TECHNICAL: unconditional root item (always included) ---
        bom_base_policy = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="POL-BASE",
            description="Base policy document package",
            category="Policy",
            quantity=1,
            unit_of_measure="pcs",
            sequence=10,
        )

        # --- TECHNICAL: nested sub-assembly (unconditional) ---
        bom_liability_module = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="MOD-LIABILITY",
            description="Liability coverage module",
            category="Coverage",
            quantity=1,
            unit_of_measure="pcs",
            sequence=20,
        )

        # --- TECHNICAL: conditional child (included when vehicle value > 50k) ---
        bom_luxury_rider = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="RIDER-LUX",
            description="Luxury vehicle extended coverage rider",
            category="Coverage",
            quantity=1,
            unit_of_measure="pcs",
            sequence=10,
        )

        # --- TECHNICAL: conditional item with multiple rules (OR logic) ---
        # Included when vehicle_type = TRUCK OR vehicle_value > 40000
        bom_heavy_assessment = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="ASSESS-HEAVY",
            description="Heavy risk assessment report",
            category="Assessment",
            quantity=1,
            unit_of_measure="pcs",
            sequence=30,
        )

        # --- TECHNICAL: dynamic quantity from field ---
        # Quantity derived from vehicle_value (the NUMBER field), static fallback = 1
        bom_inspection_cert = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.TECHNICAL.value,
            part_number="CERT-INSPECT",
            description="Vehicle inspection certificate",
            category="Certification",
            quantity=1,
            quantity_from_field_id=f_vehicle_value.id,
            unit_of_measure="pcs",
            sequence=40,
        )

        # --- COMMERCIAL: unconditional priced item (base premium) ---
        bom_base_premium = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="PREM-BASE",
            description="Base annual premium",
            category="Premium",
            quantity=1,
            unit_of_measure="yr",
            sequence=10,
        )

        # --- COMMERCIAL: conditional priced item (theft coverage add-on) ---
        bom_theft_addon = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="ADDON-THEFT",
            description="Theft & fire coverage add-on",
            category="Add-on",
            quantity=1,
            unit_of_measure="yr",
            sequence=20,
        )

        # --- COMMERCIAL: same part_number as TECHNICAL (different BOM type) ---
        bom_base_policy_comm = BOMItem(
            entity_version_id=version.id,
            bom_type=BOMType.COMMERCIAL.value,
            part_number="POL-BASE",
            description="Policy document processing fee",
            category="Fee",
            quantity=1,
            unit_of_measure="pcs",
            sequence=30,
        )

        all_bom_items = [
            bom_base_policy,
            bom_liability_module,
            bom_luxury_rider,
            bom_heavy_assessment,
            bom_inspection_cert,
            bom_base_premium,
            bom_theft_addon,
            bom_base_policy_comm,
        ]
        db.add_all(all_bom_items)
        db.flush()

        # Set parent relationships (requires IDs from flush)
        bom_luxury_rider.parent_bom_item_id = bom_liability_module.id

        db.flush()

        # --- BOM Item Rules ---

        # Luxury rider: included when vehicle value > 50000
        bomr_luxury = BOMItemRule(
            bom_item_id=bom_luxury_rider.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_vehicle_value.id, "operator": "GREATER_THAN", "value": 50000}]},
            description="Luxury rider for high-value vehicles",
        )

        # Heavy assessment rule 1: vehicle_type = TRUCK (OR logic — any rule passing includes the item)
        bomr_heavy_truck = BOMItemRule(
            bom_item_id=bom_heavy_assessment.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_vehicle_type.id, "operator": "EQUALS", "value": "TRUCK"}]},
            description="Heavy assessment for trucks",
        )

        # Heavy assessment rule 2: vehicle_value > 40000 (OR with rule above)
        bomr_heavy_value = BOMItemRule(
            bom_item_id=bom_heavy_assessment.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_vehicle_value.id, "operator": "GREATER_THAN", "value": 40000}]},
            description="Heavy assessment for high-value vehicles",
        )

        # Theft add-on: included when theft coverage is selected (not "NO")
        bomr_theft = BOMItemRule(
            bom_item_id=bom_theft_addon.id,
            entity_version_id=version.id,
            conditions={"criteria": [{"field_id": f_theft_coverage.id, "operator": "NOT_EQUALS", "value": "NO"}]},
            description="Theft add-on when coverage selected",
        )

        all_bom_rules = [bomr_luxury, bomr_heavy_truck, bomr_heavy_value, bomr_theft]
        db.add_all(all_bom_rules)
        db.commit()

        print(
            f"[7/10] BOM created: {len(all_bom_items)} items "
            f"({sum(1 for b in all_bom_items if b.bom_type == BOMType.TECHNICAL.value)} TECHNICAL, "
            f"{sum(1 for b in all_bom_items if b.bom_type == BOMType.COMMERCIAL.value)} COMMERCIAL), "
            f"{len(all_bom_rules)} rules"
        )

        # ============================================================
        # 8. PRICE LIST (demo price list for COMMERCIAL BOM items)
        # ============================================================

        price_list = PriceList(
            name="Auto Insurance Price List 2026",
            description="Standard pricing for auto insurance products — valid all of 2026",
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
        )
        db.add(price_list)
        db.flush()

        pli_base_premium = PriceListItem(
            price_list_id=price_list.id,
            part_number="PREM-BASE",
            description="Base annual premium",
            unit_price=350,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
        )
        pli_theft_addon = PriceListItem(
            price_list_id=price_list.id,
            part_number="ADDON-THEFT",
            description="Theft & fire coverage add-on",
            unit_price=89.99,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
        )
        pli_pol_base = PriceListItem(
            price_list_id=price_list.id,
            part_number="POL-BASE",
            description="Policy document processing fee",
            unit_price=15,
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
        )

        all_price_list_items = [pli_base_premium, pli_theft_addon, pli_pol_base]
        db.add_all(all_price_list_items)
        db.commit()
        print(f"[8/10] Price list created: '{price_list.name}' with {len(all_price_list_items)} items")

        # ============================================================
        # 9. USERS (3 demo users, one per role)
        # ============================================================
        # Same demo password for all: "password123"  # noqa: S105
        demo_password_hash = get_password_hash("password123")

        user_admin = User(
            email="admin@demo.com", hashed_password=demo_password_hash, role=UserRole.ADMIN.value, is_active=True
        )
        user_author = User(
            email="author@demo.com", hashed_password=demo_password_hash, role=UserRole.AUTHOR.value, is_active=True
        )
        user_demo = User(
            email="user@demo.com", hashed_password=demo_password_hash, role=UserRole.USER.value, is_active=True
        )

        all_users = [user_admin, user_author, user_demo]
        db.add_all(all_users)
        db.commit()
        print(f"[9/10] Users created: {len(all_users)} users (admin, author, user) — password: password123")

        # ============================================================
        # 10. CONFIGURATIONS (sample quotes)
        # ============================================================

        # Config 1: FINALIZED — Complete retiree car quote (closed)
        config_finalized = Configuration(
            entity_version_id=version.id,
            user_id=user_demo.id,
            created_by_id=user_demo.id,
            name="Retiree Car Quote — Complete",
            status=ConfigurationStatus.FINALIZED.value,
            is_complete=True,
            price_list_id=price_list.id,
            generated_sku="POL-AUTO-P-A-ST-50M-INF2-FI-AS3-R7",
            data=[
                {"field_id": f_name.id, "value": "John Smith"},
                {"field_id": f_dob.id, "value": "1958-03-15"},
                {"field_id": f_occupation.id, "value": "RETIRED"},
                {"field_id": f_vehicle_type.id, "value": "CAR"},
                {"field_id": f_vehicle_value.id, "value": 45000},
                {"field_id": f_satellite_tracker.id, "value": True},
                {"field_id": f_liability_limit.id, "value": "VIP"},
                {"field_id": f_injury_coverage.id, "value": "FULL"},
                {"field_id": f_theft_coverage.id, "value": "FULL"},
                {"field_id": f_roadside.id, "value": "PREMIUM"},
                {"field_id": f_rental_car.id, "value": "7D"},
            ],
        )

        # Config 2: DRAFT — Truck quote in progress (incomplete)
        config_draft = Configuration(
            entity_version_id=version.id,
            user_id=user_demo.id,
            created_by_id=user_demo.id,
            name="Truck Quote — In Progress",
            status=ConfigurationStatus.DRAFT.value,
            is_complete=False,
            price_list_id=price_list.id,
            generated_sku="POL-AUTO-C-TN-ST-25M",
            data=[
                {"field_id": f_name.id, "value": "Express Logistics LLC"},
                {"field_id": f_dob.id, "value": "1975-11-20"},
                {"field_id": f_occupation.id, "value": "SELF_EMPLOYED"},
                {"field_id": f_vehicle_type.id, "value": "TRUCK"},
                {"field_id": f_vehicle_value.id, "value": 35000},
                {"field_id": f_cargo_type.id, "value": "STANDARD"},
                {"field_id": f_liability_limit.id, "value": "HIGH"},
            ],
        )

        # Config 3: DRAFT — Student motorcycle quote (partial)
        config_draft_moto = Configuration(
            entity_version_id=version.id,
            user_id=user_demo.id,
            created_by_id=user_demo.id,
            name="Student Motorcycle Quote",
            status=ConfigurationStatus.DRAFT.value,
            is_complete=False,
            price_list_id=price_list.id,
            generated_sku=None,
            data=[
                {"field_id": f_name.id, "value": "Alex Johnson"},
                {"field_id": f_dob.id, "value": "2002-06-10"},
                {"field_id": f_occupation.id, "value": "STUDENT"},
                {"field_id": f_vehicle_type.id, "value": "MOTORCYCLE"},
                {"field_id": f_vehicle_value.id, "value": 5000},
            ],
        )

        all_configs = [config_finalized, config_draft, config_draft_moto]
        db.add_all(all_configs)
        db.commit()
        print(f"[10/10] Configurations created: {len(all_configs)} (1 FINALIZED + 2 DRAFT)")

        # ============================================================
        # SUMMARY
        # ============================================================
        print("\n" + "=" * 70)
        print("SEED COMPLETED SUCCESSFULLY")
        print("=" * 70)
        print(f"""
SUMMARY:
  Entity ID:      {entity.id}
  Version ID:     {version.id}
  SKU Base:       {version.sku_base}
  SKU Delimiter:  '{version.sku_delimiter}'

  Fields:         {len(all_fields)}
  Values:         {len(all_values)}
  Rules:          {len(all_rules)}
  BOM Items:      {len(all_bom_items)}
  BOM Rules:      {len(all_bom_rules)}
  Price Lists:    1
  Price Items:    {len(all_price_list_items)}
  Users:          {len(all_users)}
  Configurations: {len(all_configs)}

DEMO USERS (password: password123):
  admin@demo.com   — ADMIN  (full access)
  author@demo.com  — AUTHOR (create/edit entities and rules)
  user@demo.com    — USER   (create/edit configurations)

DEMO CONFIGURATIONS (user: user@demo.com):
  1. "{config_finalized.name}" [FINALIZED, complete]
     SKU: {config_finalized.generated_sku}
  2. "{config_draft.name}" [DRAFT, incomplete]
     SKU: {config_draft.generated_sku}
  3. "{config_draft_moto.name}" [DRAFT, partial]
     No SKU (missing fields)

FEATURE COVERAGE:
  Rule types:     6/6 (VISIBILITY, CALCULATION, AVAILABILITY, EDITABILITY, MANDATORY, VALIDATION)
  Operators:      7/7 (EQUALS, NOT_EQUALS, GT, GTE, LT, LTE, IN)
  Field types:    4/4 (string, number, boolean, date)
  SKU features:   sku_base + sku_modifier (Values)
  Field defaults: default_value on free-value field (additional_notes)
  BOM types:      2/2 (TECHNICAL, COMMERCIAL)
  BOM features:   hierarchy (nested sub-assembly), dynamic quantity,
                  conditional inclusion, OR logic (multiple rules),
                  same part_number in TECHNICAL + COMMERCIAL
  Price list:     temporal validity, price resolution at calculation time

CALCULATION (engine-derived dropdown):
  ┌─────────────────────────────────────────────────────┐
  │ Vehicle Value → Estimated Premium Tier (dropdown)   │
  │   <= $15,000     → ECONOMY  (SKU: EC)               │
  │   $15,001-50,000 → STANDARD (SKU: ST)               │
  │   > $50,000      → PREMIUM  (SKU: PR)               │
  │   Non-free field: available_options = forced value   │
  └─────────────────────────────────────────────────────┘

CASCADING CHAINS:

  Chain 1: Truck → Cargo Type → ADR Certification
  ┌─────────────────────────────────────────────────────┐
  │ Vehicle Type = TRUCK                                │
  │         ↓ (visibility + mandatory)                  │
  │ Cargo Type [STANDARD | REFRIGERATED | HAZARDOUS]    │
  │         ↓ (visibility + mandatory) if HAZARDOUS     │
  │ ADR Certification [BASIC | TANKS | EXPLOSIVES]      │
  └─────────────────────────────────────────────────────┘

  Chain 2: Premium Assistance → Rental Car
  ┌─────────────────────────────────────────────────────┐
  │ Roadside Assistance = PREMIUM                       │
  │         ↓ (visibility)                              │
  │ Rental Car [3D | 7D | 15D]                          │
  │         ↓ (availability) 15D only if value >= $40k  │
  └─────────────────────────────────────────────────────┘

EDITABILITY + IN OPERATOR:
  ┌─────────────────────────────────────────────────────┐
  │ Additional Notes (readonly by default)              │
  │   Occupation IN [EMPLOYEE, SELF_EMPLOYED] → editable│
  │   Retired/Student → stays readonly                  │
  └─────────────────────────────────────────────────────┘

BOM ITEMS:
  TECHNICAL (5 items):
    POL-BASE          Base policy document (unconditional, root)
    MOD-LIABILITY     Liability coverage module (unconditional, root)
      RIDER-LUX       Luxury vehicle rider (child, conditional: value > $50k)
    ASSESS-HEAVY     Heavy risk assessment (conditional: OR logic, truck OR value > $40k)
    CERT-INSPECT     Inspection certificate (dynamic quantity from vehicle_value field)
  COMMERCIAL (3 items — prices from price list):
    PREM-BASE        Base annual premium (unconditional)
    ADDON-THEFT      Theft coverage add-on (conditional: theft != NO)
    POL-BASE         Policy document fee (same part_number as TECHNICAL)

PRICE LIST:
  '{price_list.name}' (valid {price_list.valid_from} to {price_list.valid_to})
    PREM-BASE:    $350.00
    ADDON-THEFT:  $89.99
    POL-BASE:     $15.00

SKU EXAMPLES:

  1. Basic car (employee, value $10k, minimum, no extras):
     → POL-AUTO-A-EC-6M

  2. Full car (retired, value $45k, premium, injury, theft, assistance):
     → POL-AUTO-P-A-ST-50M-INF2-FI-AS3-R7

  3. Truck with hazardous goods (ADR tanks, high limit):
     → POL-AUTO-C-TN-ST-25M  (standard goods)
     → POL-AUTO-C-TP-ADR2-ST-25M  (hazardous with ADR tanks)

  4. Motorcycle (no injury, no full theft):
     → POL-AUTO-M-EC-10M
""")
        print("=" * 70)

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    seed_db()
