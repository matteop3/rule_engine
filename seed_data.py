import sys
import os
from datetime import date

# Fix path per importare i moduli app dalla root
sys.path.append(os.getcwd())

from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app.models.domain import (
    Entity, EntityVersion, Field, Value, Rule,
    RuleType, FieldType, VersionStatus
)


def seed_db():
    db = SessionLocal()
    try:
        print("=" * 70)
        print("SEED DATA - Polizza Auto Gold (Extended con Cascading Rules)")
        print("=" * 70)

        # 1. Pulizia
        db.query(Rule).delete()
        db.query(Value).delete()
        db.query(Field).delete()
        db.query(EntityVersion).delete()
        db.query(Entity).delete()
        db.commit()
        print("\n[1/7] Database pulito.")

        # 2. Entity
        entity = Entity(
            name="Polizza Auto Gold",
            description="Configuratore preventivi auto completo con regole a cascata"
        )
        db.add(entity)
        db.commit()
        print(f"[2/7] Entity creata: {entity.name} (ID: {entity.id})")

        # 3. Version (con SKU configuration)
        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Versione completa con cascading rules e SKU generation",
            sku_base="POL-AUTO",
            sku_delimiter="-"
        )
        db.add(version)
        db.commit()
        print(f"[3/7] Version creata: v{version.version_number} (SKU: {version.sku_base})")

        # ============================================================
        # 4. FIELDS (12 campi in 4 steps)
        # ============================================================

        # --- STEP 1: Dati Contraente ---
        f_nome = Field(
            entity_version_id=version.id,
            name="contraente_nome",
            label="Nome Completo",
            data_type=FieldType.STRING.value,
            is_free_value=True,
            step=1, sequence=10,
            is_required=True
        )

        f_nascita = Field(
            entity_version_id=version.id,
            name="contraente_nascita",
            label="Data di Nascita",
            data_type=FieldType.DATE.value,
            is_free_value=True,
            step=1, sequence=20,
            is_required=True
        )

        f_professione = Field(
            entity_version_id=version.id,
            name="contraente_professione",
            label="Professione",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=1, sequence=30,
            is_required=True
        )

        # --- STEP 2: Dati Veicolo ---
        f_tipo = Field(
            entity_version_id=version.id,
            name="veicolo_tipo",
            label="Tipologia Mezzo",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=2, sequence=10,
            is_required=True
        )

        f_valore = Field(
            entity_version_id=version.id,
            name="veicolo_valore",
            label="Valore Veicolo (€)",
            data_type=FieldType.NUMBER.value,
            is_free_value=True,
            step=2, sequence=20,
            is_required=True
        )

        f_satellitare = Field(
            entity_version_id=version.id,
            name="veicolo_antifurto",
            label="Antifurto Satellitare?",
            data_type=FieldType.BOOLEAN.value,
            is_free_value=True,
            step=2, sequence=30
        )

        # --- CASCADING CHAIN 1: Camion → Tipo Trasporto → Certificazione ADR ---
        # Questi campi sono visibili solo se si seleziona CAMION
        f_tipo_trasporto = Field(
            entity_version_id=version.id,
            name="camion_tipo_trasporto",
            label="Tipo di Trasporto",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_hidden=True,  # Nascosto di default, visibile solo per CAMION
            step=2, sequence=40,
            is_required=False  # Diventa required dinamicamente
        )

        f_certificazione_adr = Field(
            entity_version_id=version.id,
            name="camion_certificazione_adr",
            label="Certificazione ADR",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_hidden=True,  # Nascosto di default, visibile solo per merci pericolose
            step=2, sequence=50,
            is_required=False  # Diventa required dinamicamente
        )

        # --- STEP 3: Coperture Base ---
        f_massimale = Field(
            entity_version_id=version.id,
            name="polizza_massimale",
            label="Massimale RC",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=3, sequence=10,
            is_required=True
        )

        f_infortuni = Field(
            entity_version_id=version.id,
            name="polizza_infortuni",
            label="Copertura Infortuni",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=3, sequence=20
        )

        f_furto = Field(
            entity_version_id=version.id,
            name="polizza_furto",
            label="Copertura Furto/Incendio",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=3, sequence=30
        )

        # --- STEP 4: Servizi Aggiuntivi (CASCADING CHAIN 2) ---
        # Assistenza Stradale → Auto Sostitutiva (visibile solo con assistenza premium)
        f_assistenza = Field(
            entity_version_id=version.id,
            name="servizi_assistenza",
            label="Assistenza Stradale",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            step=4, sequence=10
        )

        f_auto_sostitutiva = Field(
            entity_version_id=version.id,
            name="servizi_auto_sostitutiva",
            label="Auto Sostitutiva",
            data_type=FieldType.STRING.value,
            is_free_value=False,
            is_hidden=True,  # Visibile solo con assistenza PREMIUM
            step=4, sequence=20
        )

        all_fields = [
            f_nome, f_nascita, f_professione,
            f_tipo, f_valore, f_satellitare, f_tipo_trasporto, f_certificazione_adr,
            f_massimale, f_infortuni, f_furto,
            f_assistenza, f_auto_sostitutiva
        ]
        db.add_all(all_fields)
        db.commit()
        print(f"[4/7] Campi creati: {len(all_fields)} fields in 4 steps")

        # ============================================================
        # 5. VALUES (con SKU modifiers)
        # ============================================================

        # --- Professione ---
        v_prof_dip = Value(field_id=f_professione.id, label="Dipendente", value="DIPENDENTE",
                          is_default=True, sku_modifier=None)
        v_prof_aut = Value(field_id=f_professione.id, label="Autonomo/Libero Prof.", value="AUTONOMO",
                          sku_modifier=None)
        v_prof_pens = Value(field_id=f_professione.id, label="Pensionato", value="PENSIONATO",
                           sku_modifier="P")  # Sconto pensionati → marker nel codice
        v_prof_stud = Value(field_id=f_professione.id, label="Studente", value="STUDENTE",
                           sku_modifier="S")  # Sconto studenti → marker nel codice

        # --- Tipo Veicolo ---
        v_auto = Value(field_id=f_tipo.id, label="Automobile", value="AUTO",
                      is_default=True, sku_modifier="A")
        v_moto = Value(field_id=f_tipo.id, label="Motociclo", value="MOTO",
                      sku_modifier="M")
        v_camion = Value(field_id=f_tipo.id, label="Autocarro", value="CAMION",
                        sku_modifier="C")
        v_furgone = Value(field_id=f_tipo.id, label="Furgone", value="FURGONE",
                         sku_modifier="F")

        # --- Tipo Trasporto (solo per CAMION) ---
        v_trasp_normale = Value(field_id=f_tipo_trasporto.id, label="Merci Normali", value="NORMALE",
                               is_default=True, sku_modifier="TN")
        v_trasp_refrig = Value(field_id=f_tipo_trasporto.id, label="Merci Refrigerate", value="REFRIGERATO",
                              sku_modifier="TR")
        v_trasp_peric = Value(field_id=f_tipo_trasporto.id, label="Merci Pericolose (ADR)", value="PERICOLOSO",
                             sku_modifier="TP")

        # --- Certificazione ADR (solo per merci pericolose) ---
        v_adr_base = Value(field_id=f_certificazione_adr.id, label="ADR Base", value="ADR_BASE",
                          is_default=True, sku_modifier="ADR1")
        v_adr_cisterne = Value(field_id=f_certificazione_adr.id, label="ADR Cisterne", value="ADR_CISTERNE",
                               sku_modifier="ADR2")
        v_adr_esplosivi = Value(field_id=f_certificazione_adr.id, label="ADR Esplosivi (Classe 1)", value="ADR_ESPLOSIVI",
                                sku_modifier="ADR3")

        # --- Massimale RC ---
        v_mass_base = Value(field_id=f_massimale.id, label="Minimo di Legge (6M)", value="MINIMO",
                           is_default=True, sku_modifier="6M")
        v_mass_med = Value(field_id=f_massimale.id, label="Standard (10M)", value="STANDARD",
                          sku_modifier="10M")
        v_mass_high = Value(field_id=f_massimale.id, label="Elevato (25M)", value="ELEVATO",
                           sku_modifier="25M")
        v_mass_vip = Value(field_id=f_massimale.id, label="Premium (50M)", value="VIP",
                          sku_modifier="50M")

        # --- Copertura Infortuni ---
        v_infortuni_no = Value(field_id=f_infortuni.id, label="Non inclusa", value="NO",
                              is_default=True, sku_modifier=None)
        v_infortuni_base = Value(field_id=f_infortuni.id, label="Base (50k)", value="BASE",
                                sku_modifier="INF1")
        v_infortuni_full = Value(field_id=f_infortuni.id, label="Completa (100k)", value="FULL",
                                sku_modifier="INF2")

        # --- Copertura Furto/Incendio ---
        v_furto_no = Value(field_id=f_furto.id, label="Non inclusa", value="NO",
                          is_default=True, sku_modifier=None)
        v_furto_inc = Value(field_id=f_furto.id, label="Solo Incendio", value="INCENDIO",
                           sku_modifier="INC")
        v_furto_full = Value(field_id=f_furto.id, label="Furto + Incendio", value="FULL",
                            sku_modifier="FI")

        # --- Assistenza Stradale ---
        v_assist_no = Value(field_id=f_assistenza.id, label="Non inclusa", value="NO",
                           is_default=True, sku_modifier=None)
        v_assist_base = Value(field_id=f_assistenza.id, label="Base (solo traino)", value="BASE",
                             sku_modifier="AS1")
        v_assist_plus = Value(field_id=f_assistenza.id, label="Plus (traino + taxi)", value="PLUS",
                             sku_modifier="AS2")
        v_assist_premium = Value(field_id=f_assistenza.id, label="Premium (tutto incluso)", value="PREMIUM",
                                sku_modifier="AS3")

        # --- Auto Sostitutiva (solo con assistenza PREMIUM) ---
        v_auto_sost_no = Value(field_id=f_auto_sostitutiva.id, label="Non inclusa", value="NO",
                              is_default=True, sku_modifier=None)
        v_auto_sost_3g = Value(field_id=f_auto_sostitutiva.id, label="3 giorni", value="3G",
                              sku_modifier="R3")
        v_auto_sost_7g = Value(field_id=f_auto_sostitutiva.id, label="7 giorni", value="7G",
                              sku_modifier="R7")
        v_auto_sost_15g = Value(field_id=f_auto_sostitutiva.id, label="15 giorni", value="15G",
                               sku_modifier="R15")

        all_values = [
            v_prof_dip, v_prof_aut, v_prof_pens, v_prof_stud,
            v_auto, v_moto, v_camion, v_furgone,
            v_trasp_normale, v_trasp_refrig, v_trasp_peric,
            v_adr_base, v_adr_cisterne, v_adr_esplosivi,
            v_mass_base, v_mass_med, v_mass_high, v_mass_vip,
            v_infortuni_no, v_infortuni_base, v_infortuni_full,
            v_furto_no, v_furto_inc, v_furto_full,
            v_assist_no, v_assist_base, v_assist_plus, v_assist_premium,
            v_auto_sost_no, v_auto_sost_3g, v_auto_sost_7g, v_auto_sost_15g
        ]
        db.add_all(all_values)
        db.commit()
        print(f"[5/7] Valori creati: {len(all_values)} values con SKU modifiers")

        # ============================================================
        # 6. RULES (15 regole incluse cascading chains)
        # ============================================================

        # --- VALIDATION: Maggiorenne ---
        today = date.today()
        maggiore_eta = today.replace(year=today.year - 18)

        r_minorenne = Rule(
            entity_version_id=version.id,
            target_field_id=f_nascita.id,
            rule_type=RuleType.VALIDATION.value,
            description="Blocca minorenni",
            error_message="Il contraente deve essere maggiorenne.",
            conditions={"criteria": [
                {"field_id": f_nascita.id, "operator": "GREATER_THAN", "value": str(maggiore_eta)}
            ]}
        )

        # --- VALIDATION: Valore minimo veicolo ---
        r_valore_minimo = Rule(
            entity_version_id=version.id,
            target_field_id=f_valore.id,
            rule_type=RuleType.VALIDATION.value,
            description="Valore minimo veicolo",
            error_message="Il valore del veicolo deve essere almeno 1000€.",
            conditions={"criteria": [
                {"field_id": f_valore.id, "operator": "LESS_THAN", "value": 1000}
            ]}
        )

        # --- VALIDATION: Valore massimo per studenti ---
        r_valore_max_studenti = Rule(
            entity_version_id=version.id,
            target_field_id=f_valore.id,
            rule_type=RuleType.VALIDATION.value,
            description="Studenti: valore max 30k",
            error_message="Per studenti il valore max assicurabile è 30.000€.",
            conditions={"criteria": [
                {"field_id": f_professione.id, "operator": "EQUALS", "value": "STUDENTE"},
                {"field_id": f_valore.id, "operator": "GREATER_THAN", "value": 30000}
            ]}
        )

        # --- MANDATORY: Satellitare obbligatorio per veicoli > 50k ---
        r_mand_satellitare = Rule(
            entity_version_id=version.id,
            target_field_id=f_satellitare.id,
            rule_type=RuleType.MANDATORY.value,
            description="Satellitare obbligatorio per veicoli di lusso",
            conditions={"criteria": [
                {"field_id": f_valore.id, "operator": "GREATER_THAN", "value": 50000}
            ]}
        )

        # --- EDITABILITY: Satellitare readonly con VIP (incluso nel pacchetto) ---
        r_readonly_sat_vip = Rule(
            entity_version_id=version.id,
            target_field_id=f_satellitare.id,
            rule_type=RuleType.EDITABILITY.value,
            description="Satellitare incluso nel pacchetto Premium",
            conditions={"criteria": [
                {"field_id": f_massimale.id, "operator": "NOT_EQUALS", "value": "VIP"}
            ]}
        )

        # ============================================================
        # CASCADING CHAIN 1: Camion → Tipo Trasporto → Certificazione ADR
        # ============================================================

        # STEP 1: Mostra "Tipo Trasporto" solo se veicolo = CAMION
        r_show_tipo_trasporto = Rule(
            entity_version_id=version.id,
            target_field_id=f_tipo_trasporto.id,
            rule_type=RuleType.VISIBILITY.value,
            description="[CHAIN 1.1] Tipo trasporto visibile solo per Camion",
            conditions={"criteria": [
                {"field_id": f_tipo.id, "operator": "EQUALS", "value": "CAMION"}
            ]}
        )

        # STEP 1b: Tipo Trasporto diventa required per CAMION
        r_mand_tipo_trasporto = Rule(
            entity_version_id=version.id,
            target_field_id=f_tipo_trasporto.id,
            rule_type=RuleType.MANDATORY.value,
            description="[CHAIN 1.1b] Tipo trasporto obbligatorio per Camion",
            conditions={"criteria": [
                {"field_id": f_tipo.id, "operator": "EQUALS", "value": "CAMION"}
            ]}
        )

        # STEP 2: Mostra "Certificazione ADR" solo se trasporto = PERICOLOSO
        # Questa regola dipende dal campo precedente (tipo_trasporto) che è già stato processato
        r_show_adr = Rule(
            entity_version_id=version.id,
            target_field_id=f_certificazione_adr.id,
            rule_type=RuleType.VISIBILITY.value,
            description="[CHAIN 1.2] ADR visibile solo per merci pericolose",
            conditions={"criteria": [
                {"field_id": f_tipo_trasporto.id, "operator": "EQUALS", "value": "PERICOLOSO"}
            ]}
        )

        # STEP 2b: Certificazione ADR obbligatoria per merci pericolose
        r_mand_adr = Rule(
            entity_version_id=version.id,
            target_field_id=f_certificazione_adr.id,
            rule_type=RuleType.MANDATORY.value,
            description="[CHAIN 1.2b] ADR obbligatorio per merci pericolose",
            conditions={"criteria": [
                {"field_id": f_tipo_trasporto.id, "operator": "EQUALS", "value": "PERICOLOSO"}
            ]}
        )

        # ============================================================
        # CASCADING CHAIN 2: Assistenza Premium → Auto Sostitutiva
        # ============================================================

        # Mostra "Auto Sostitutiva" solo se assistenza = PREMIUM
        r_show_auto_sost = Rule(
            entity_version_id=version.id,
            target_field_id=f_auto_sostitutiva.id,
            rule_type=RuleType.VISIBILITY.value,
            description="[CHAIN 2.1] Auto sostitutiva solo con assistenza Premium",
            conditions={"criteria": [
                {"field_id": f_assistenza.id, "operator": "EQUALS", "value": "PREMIUM"}
            ]}
        )

        # ============================================================
        # AVAILABILITY RULES
        # ============================================================

        # No Massimale Minimo per Camion (veicoli commerciali)
        r_no_minimo_camion = Rule(
            entity_version_id=version.id,
            target_field_id=f_massimale.id,
            target_value_id=v_mass_base.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="No massimale minimo per camion",
            conditions={"criteria": [
                {"field_id": f_tipo.id, "operator": "NOT_EQUALS", "value": "CAMION"}
            ]}
        )

        # No Furto per Moto (statisticamente sfavorevole)
        r_no_furto_moto = Rule(
            entity_version_id=version.id,
            target_field_id=f_furto.id,
            target_value_id=v_furto_full.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="Copertura furto completa non disponibile per moto",
            conditions={"criteria": [
                {"field_id": f_tipo.id, "operator": "NOT_EQUALS", "value": "MOTO"}
            ]}
        )

        # No Infortuni per Moto
        r_hide_infortuni_moto = Rule(
            entity_version_id=version.id,
            target_field_id=f_infortuni.id,
            rule_type=RuleType.VISIBILITY.value,
            description="No copertura infortuni per Moto",
            conditions={"criteria": [
                {"field_id": f_tipo.id, "operator": "NOT_EQUALS", "value": "MOTO"}
            ]}
        )

        # Auto sostitutiva 15g solo per veicoli > 40k
        r_auto_sost_15g_luxury = Rule(
            entity_version_id=version.id,
            target_field_id=f_auto_sostitutiva.id,
            target_value_id=v_auto_sost_15g.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="Auto sostitutiva 15g solo per veicoli di lusso",
            conditions={"criteria": [
                {"field_id": f_valore.id, "operator": "GREATER_THAN_OR_EQUAL", "value": 40000}
            ]}
        )

        all_rules = [
            # Validation
            r_minorenne, r_valore_minimo, r_valore_max_studenti,
            # Mandatory & Editability
            r_mand_satellitare, r_readonly_sat_vip,
            # Cascading Chain 1: Camion → Trasporto → ADR
            r_show_tipo_trasporto, r_mand_tipo_trasporto,
            r_show_adr, r_mand_adr,
            # Cascading Chain 2: Assistenza → Auto Sostitutiva
            r_show_auto_sost,
            # Availability
            r_no_minimo_camion, r_no_furto_moto, r_hide_infortuni_moto,
            r_auto_sost_15g_luxury
        ]
        db.add_all(all_rules)
        db.commit()
        print(f"[6/7] Regole create: {len(all_rules)} rules (incluse 2 cascading chains)")

        # ============================================================
        # RIEPILOGO
        # ============================================================
        print("\n" + "=" * 70)
        print("[7/7] SEED COMPLETATO CON SUCCESSO")
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

CASCADING CHAINS:

  Chain 1: Camion → Tipo Trasporto → Certificazione ADR
  ┌─────────────────────────────────────────────────────┐
  │ Tipo Veicolo = CAMION                               │
  │         ↓ (visibility + mandatory)                  │
  │ Tipo Trasporto [NORMALE | REFRIGERATO | PERICOLOSO] │
  │         ↓ (visibility + mandatory) se PERICOLOSO    │
  │ Certificazione ADR [BASE | CISTERNE | ESPLOSIVI]    │
  └─────────────────────────────────────────────────────┘

  Chain 2: Assistenza Premium → Auto Sostitutiva
  ┌─────────────────────────────────────────────────────┐
  │ Assistenza Stradale = PREMIUM                       │
  │         ↓ (visibility)                              │
  │ Auto Sostitutiva [3G | 7G | 15G]                    │
  │         ↓ (availability) 15G solo se valore >= 40k  │
  └─────────────────────────────────────────────────────┘

ESEMPI SKU:

  1. Auto base (dipendente, minimo, niente extra):
     → POL-AUTO-A-6M

  2. Auto completa (pensionato, premium, infortuni, furto, assistenza):
     → POL-AUTO-P-A-50M-INF2-FI-AS3-R7

  3. Camion merci pericolose (ADR cisterne, elevato):
     → POL-AUTO-C-TN-25M  (merci normali)
     → POL-AUTO-C-TP-ADR2-25M  (pericolose con ADR cisterne)

  4. Moto standard (no infortuni, no furto full):
     → POL-AUTO-M-10M
""")
        print("=" * 70)

    except Exception as e:
        print(f"\nERRORE: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    seed_db()
