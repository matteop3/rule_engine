import sys
import os

# Aggiunge la root del progetto al path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from app.database import SessionLocal, engine, Base
# Importiamo le classi dal TUO domain.py
from app.models.domain import (
    Entity, EntityVersion, VersionStatus, 
    Field, Value, Rule, 
    User, UserRole, Configuration
)
from app.core.security import get_password_hash

def init_db():
    # 1. Crea le tabelle
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # Pulizia completa (ordine inverso per via delle foreign keys)
        print("--- 🧹 PULIZIA DATABASE ---")
        db.query(Configuration).delete()
        db.query(Rule).delete()
        db.query(Value).delete()
        db.query(Field).delete()
        db.query(EntityVersion).delete()
        db.query(Entity).delete()
        db.query(User).delete()
        db.commit()

        print("--- 🌱 INIZIO SEEDING (Corretto) ---")

        # ---------------------------------------------------------
        # 1. CREAZIONE UTENTI
        # ---------------------------------------------------------
        print("1. Creazione Utenti...")
        
        user_admin = User(
            email="admin@example.com",
            hashed_password=get_password_hash("admin123"),
            role=UserRole.ADMIN,
            is_active=True
        )

        user_author = User(
            email="author@example.com",
            hashed_password=get_password_hash("author123"),
            role=UserRole.AUTHOR,
            is_active=True
        )

        user_standard = User(
            email="user@example.com",
            hashed_password=get_password_hash("user123"),
            role=UserRole.USER,
            is_active=True
        )

        db.add_all([user_admin, user_author, user_standard])
        db.commit()
        print("   ✅ Utenti creati (Password: xxx123)")


        # ---------------------------------------------------------
        # 2. CREAZIONE ENTITÀ
        # ---------------------------------------------------------
        print("2. Creazione Entità...")
        car_entity = Entity(name="Auto Sportiva", description="Configuratore Supercar")
        db.add(car_entity)
        db.commit()
        
        # ---------------------------------------------------------
        # 3. CREAZIONE VERSIONE
        # ---------------------------------------------------------
        print("3. Creazione Versione Published...")
        v1 = EntityVersion(
            entity_id=car_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Initial Release"
        )
        db.add(v1)
        db.commit()

        # ---------------------------------------------------------
        # 4. CREAZIONE CAMPI (Fields)
        # CORREZIONE: Rimossa proprietà 'label' che non esiste nel model
        # ---------------------------------------------------------
        print("4. Creazione Campi...")
        
        # Campo 1: Modello
        f_model = Field(
            entity_version_id=v1.id,
            name="model",  # Nome interno (usato anche come label dal FE se manca label esplicita)
            step=1, sequence=10, is_required=True,
            data_type="select"
        )
        
        # Campo 2: Motore
        f_engine = Field(
            entity_version_id=v1.id,
            name="engine", 
            step=1, sequence=20, is_required=True,
            data_type="radio"
        )
        
        # Campo 3: Colore
        f_color = Field(
            entity_version_id=v1.id,
            name="color", 
            step=2, sequence=10, is_required=True,
            data_type="select"
        )

        db.add_all([f_model, f_engine, f_color])
        db.commit()

        # ---------------------------------------------------------
        # 5. CREAZIONE VALORI (Values)
        # Qui 'label' esiste nel model, quindi lo lasciamo
        # ---------------------------------------------------------
        print("5. Creazione Valori...")
        
        # Valori Modello
        v_gt = Value(field_id=f_model.id, value="GT Sport", label="GT Sport (2 Posti)")
        v_suv = Value(field_id=f_model.id, value="SUV Luxury", label="SUV Luxury (5 Posti)")
        
        # Valori Motore
        v_v6 = Value(field_id=f_engine.id, value="V6 Hybrid", label="V6 Hybrid 400hp")
        v_v8 = Value(field_id=f_engine.id, value="V8 Biturbo", label="V8 Biturbo 600hp")
        v_elec = Value(field_id=f_engine.id, value="Electric", label="Full Electric", is_default=True)

        # Valori Colore
        v_red = Value(field_id=f_color.id, value="Rosso Ferrari", label="Rosso Corsa")
        v_black = Value(field_id=f_color.id, value="Nero Opaco", label="Nero Opaco")

        db.add_all([v_gt, v_suv, v_v6, v_v8, v_elec, v_red, v_black])
        db.commit()

        # ---------------------------------------------------------
        # 6. CREAZIONE REGOLE (Rules)
        # ---------------------------------------------------------
        print("6. Creazione Regole...")

        # REGOLA 1 (Availability): V8 solo su GT Sport
        rule_v8 = Rule(
            entity_version_id=v1.id,
            target_field_id=f_engine.id,
            target_value_id=v_v8.id,
            rule_type="availability",
            description="V8 solo su GT",
            conditions={
                "criteria": [
                    {"field_id": f_model.id, "operator": "EQUALS", "value": "GT Sport"}
                ],
                "logic": "AND"
            }
        )

        # REGOLA 2 (Visibility): Colore visibile solo su GT Sport
        rule_color_vis = Rule(
            entity_version_id=v1.id,
            target_field_id=f_color.id,
            target_value_id=None,
            rule_type="visibility",
            description="Colore personalizzabile solo su GT",
            conditions={
                "criteria": [
                    {"field_id": f_model.id, "operator": "EQUALS", "value": "GT Sport"}
                ]
            }
        )

        db.add_all([rule_v8, rule_color_vis])
        db.commit()

        print("--- 🌱 SEED COMPLETATO CON SUCCESSO! ---")
        print("Credentials:")
        print("  👑 ADMIN:  admin@example.com  / admin123")
        print("  🛠️ AUTHOR: author@example.com / author123")
        print("  👤 USER:   user@example.com   / user123")

    except Exception as e:
        print(f"❌ Errore durante il seed: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    init_db()