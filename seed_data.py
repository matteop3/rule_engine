import sys
import os
from datetime import date

# Fix path per importare i moduli app dalla root
sys.path.append(os.getcwd())

from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
from app.models.domain import Entity, EntityVersion, Field, Value, Rule, RuleType, FieldType, VersionStatus

def seed_db():
    db = SessionLocal()
    try:
        print("--- INIZIO SEED DATA (Con Labels & is_free_value) ---")
        
        # 1. Pulizia
        db.query(Rule).delete()
        db.query(Value).delete()
        db.query(Field).delete()
        db.query(EntityVersion).delete()
        db.query(Entity).delete()
        db.commit()
        print("1. Database pulito.")

        # 2. Entity
        entity = Entity(
            name="Polizza Auto Gold", 
            description="Configuratore preventivi auto"
        )
        db.add(entity)
        db.commit()

        # 3. Version
        version = EntityVersion(
            entity_id=entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Versione Iniziale Produzione"
        )
        db.add(version)
        db.commit()

        # 4. Fields 
        # Logica is_free_value:
        # True  -> Input diretto (Text, Date, Number, Boolean/Checkbox)
        # False -> Dropdown (Richiede opzioni nella tabella Values)
        
        # F1: Nome (Input Testo Libero)
        f_nome = Field(
            entity_version_id=version.id, 
            name="contraente_nome",      
            label="Nome Completo",       
            data_type=FieldType.STRING.value, 
            is_free_value=True,          # <--- CORRETTO: True
            step=1, sequence=10, is_required=True
        )
        
        # F2: Data Nascita (Datepicker Libero)
        f_nascita = Field(
            entity_version_id=version.id, 
            name="contraente_nascita", 
            label="Data di Nascita", 
            data_type=FieldType.DATE.value, 
            is_free_value=True,          # <--- CORRETTO: True
            step=1, sequence=20, is_required=True
        )
        
        # F3: Tipo Veicolo (Dropdown -> False)
        f_tipo = Field(
            entity_version_id=version.id, 
            name="veicolo_tipo", 
            label="Tipologia Mezzo", 
            data_type=FieldType.STRING.value, 
            is_free_value=False,         # <--- CORRETTO: False (Ha i Value sotto)
            step=1, sequence=30, is_required=True
        )
        
        # F4: Valore Veicolo (Input Numero Libero)
        f_valore = Field(
            entity_version_id=version.id, 
            name="veicolo_valore", 
            label="Valore Veicolo (€)", 
            data_type=FieldType.NUMBER.value, 
            is_free_value=True,          # <--- CORRETTO: True
            step=2, sequence=40, is_required=True
        )
        
        # F5: Antifurto Satellitare (Checkbox/Boolean Libero)
        # Nota: I booleani sono tecnicamente "free value" (True/False) e non pescano da tabella Values
        f_satellitare = Field(
            entity_version_id=version.id, 
            name="veicolo_antifurto", 
            label="Antifurto Satellitare?", 
            data_type=FieldType.BOOLEAN.value, 
            is_free_value=True,          # <--- CORRETTO: True
            step=2, sequence=50
        )

        # F6: Massimale (Dropdown -> False)
        f_massimale = Field(
            entity_version_id=version.id, 
            name="polizza_massimale", 
            label="Massimale RC", 
            data_type=FieldType.STRING.value, 
            is_free_value=False,         # <--- CORRETTO: False
            step=2, sequence=60, is_required=True
        )

        # F7: Infortuni Conducente (Checkbox/Boolean Libero)
        f_infortuni = Field(
            entity_version_id=version.id, 
            name="polizza_infortuni", 
            label="Copertura Infortuni", 
            data_type=FieldType.BOOLEAN.value, 
            is_free_value=True,          # <--- CORRETTO: True
            step=3, sequence=70
        )

        db.add_all([f_nome, f_nascita, f_tipo, f_valore, f_satellitare, f_massimale, f_infortuni])
        db.commit()
        print("3. Campi creati (is_free_value impostato correttame).")

        # 5. Values (Restano uguali - Solo per i campi con is_free_value=False)
        v_auto = Value(field_id=f_tipo.id, label="Automobile", value="AUTO", is_default=True)
        v_moto = Value(field_id=f_tipo.id, label="Motociclo", value="MOTO")
        v_camion = Value(field_id=f_tipo.id, label="Autocarro", value="CAMION")
        
        v_mass_base = Value(field_id=f_massimale.id, label="Minimo di Legge (6M)", value="MINIMO", is_default=True)
        v_mass_med = Value(field_id=f_massimale.id, label="Standard (10M)", value="STANDARD")
        v_mass_vip = Value(field_id=f_massimale.id, label="Vip (50M)", value="VIP")

        db.add_all([v_auto, v_moto, v_camion, v_mass_base, v_mass_med, v_mass_vip])
        db.commit()
        print("4. Valori creati.")

        # 6. Regole (Non cambiano)
        
        # Minorenne
        today = date.today()
        maggiore_eta = today.replace(year=today.year - 18)
        
        r_minorenne = Rule(
            entity_version_id=version.id,
            target_field_id=f_nascita.id,
            rule_type=RuleType.VALIDATION.value,
            description="Blocca minorenni",
            error_message="Il contraente deve essere maggiorenne.",
            conditions={"criteria": [{"field_id": f_nascita.id, "operator": "GREATER_THAN", "value": str(maggiore_eta)}]}
        )

        # Hide Infortuni se Moto
        r_hide_infortuni = Rule(
            entity_version_id=version.id,
            target_field_id=f_infortuni.id,
            rule_type=RuleType.VISIBILITY.value,
            description="No infortuni per Moto",
            conditions={"criteria": [{"field_id": f_tipo.id, "operator": "NOT_EQUALS", "value": "MOTO"}]}
        )

        # No Minimo per Camion
        r_no_minimo_camion = Rule(
            entity_version_id=version.id,
            target_field_id=f_massimale.id,
            target_value_id=v_mass_base.id,
            rule_type=RuleType.AVAILABILITY.value,
            description="No massimale minimo per camion",
            conditions={"criteria": [{"field_id": f_tipo.id, "operator": "NOT_EQUALS", "value": "CAMION"}]}
        )

        # Satellitare Obbligatorio > 50k
        r_mand_satellitare = Rule(
            entity_version_id=version.id,
            target_field_id=f_satellitare.id,
            rule_type=RuleType.MANDATORY.value,
            description="Satellitare required luxury",
            conditions={"criteria": [{"field_id": f_valore.id, "operator": "GREATER_THAN", "value": 50000}]}
        )

        # Valore Minimo 1000
        r_valore_minimo = Rule(
            entity_version_id=version.id,
            target_field_id=f_valore.id,
            rule_type=RuleType.VALIDATION.value,
            description="Min value check",
            error_message="Valore minimo 1000 euro.",
            conditions={"criteria": [{"field_id": f_valore.id, "operator": "LESS_THAN", "value": 1000}]}
        )
        
        # Readonly Satellitare se VIP
        r_readonly_vip = Rule(
            entity_version_id=version.id,
            target_field_id=f_satellitare.id,
            rule_type=RuleType.EDITABILITY.value,
            description="Satellitare incluso in VIP",
            conditions={"criteria": [{"field_id": f_massimale.id, "operator": "IN", "value": ["VIP"]}]}
        )

        db.add_all([r_minorenne, r_hide_infortuni, r_no_minimo_camion, r_mand_satellitare, r_valore_minimo, r_readonly_vip])
        db.commit()
        print("5. Regole create.")
        
        print(f"--- SEED COMPLETATO. Entity ID: {entity.id} ---")

    except Exception as e:
        print(f"ERRORE: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    seed_db()