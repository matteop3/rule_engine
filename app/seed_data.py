import requests
import json
import sys

# CONFIGURAZIONE
BASE_URL = "http://localhost:8000"

def log(msg):
    print(f"[SEED] {msg}")

def check_resp(resp, context):
    if resp.status_code not in [200, 201]:
        print(f"ERROR in {context}: {resp.status_code}")
        print(resp.text)
        sys.exit(1)
    return resp.json()

def run_seed():
    log("Inizio popolamento dati di test...")

    # 1. Crea Entity
    log("Creating Entity 'Auto Sportiva'...")
    resp = requests.post(f"{BASE_URL}/entities/", json={
        "name": "Auto Sportiva",
        "description": "Configuratore per test versioning e regole"
    })
    entity = check_resp(resp, "Create Entity")
    entity_id = entity["id"]

    # 2. Crea Versione Draft
    log("Creating Version 1 (Draft)...")
    resp = requests.post(f"{BASE_URL}/versions/", json={
        "entity_id": entity_id,
        "changelog": "Initial Setup with V8 Engine rules"
    })
    version = check_resp(resp, "Create Version")
    v_id = version["id"]

    # 3. Crea Campi (Fields)
    log("Creating Fields...")
    
    # Field 1: Modello
    f_model = check_resp(requests.post(f"{BASE_URL}/fields/", json={
        "entity_version_id": v_id,
        "name": "Modello",
        "step": 1,
        "sequence": 1,
        "is_required": True
    }), "Field Modello")

    # Field 2: Motore
    f_engine = check_resp(requests.post(f"{BASE_URL}/fields/", json={
        "entity_version_id": v_id,
        "name": "Motore",
        "step": 2,
        "sequence": 1,
        "is_required": True
    }), "Field Motore")

    # Field 3: Colore
    f_color = check_resp(requests.post(f"{BASE_URL}/fields/", json={
        "entity_version_id": v_id,
        "name": "Colore",
        "step": 3,
        "sequence": 1,
        "is_required": True
    }), "Field Colore")

    # Field 4: Codice RAL (Free Text, Hidden by default)
    f_ral = check_resp(requests.post(f"{BASE_URL}/fields/", json={
        "entity_version_id": v_id,
        "name": "Codice RAL",
        "step": 3,
        "sequence": 2,
        "is_free_value": True,
        "is_hidden": True, # Nascosto di default, lo accenderemo con una regola
        "is_required": True # Se diventa visibile, è obbligatorio
    }), "Field RAL")

    # 4. Crea Valori (Values)
    log("Creating Values...")

    # Valori Modello
    v_base = check_resp(requests.post(f"{BASE_URL}/values/", json={"field_id": f_model["id"], "value": "Base", "is_default": True}), "Val Base")
    v_sport = check_resp(requests.post(f"{BASE_URL}/values/", json={"field_id": f_model["id"], "value": "GT Sport"}), "Val GT Sport")

    # Valori Motore
    v_diesel = check_resp(requests.post(f"{BASE_URL}/values/", json={"field_id": f_engine["id"], "value": "1.6 Diesel", "is_default": True}), "Val Diesel")
    v_v8 = check_resp(requests.post(f"{BASE_URL}/values/", json={"field_id": f_engine["id"], "value": "V8 Biturbo"}), "Val V8")

    # Valori Colore
    v_white = check_resp(requests.post(f"{BASE_URL}/values/", json={"field_id": f_color["id"], "value": "Bianco", "is_default": True}), "Val Bianco")
    v_red = check_resp(requests.post(f"{BASE_URL}/values/", json={"field_id": f_color["id"], "value": "Rosso Ferrari"}), "Val Rosso")
    v_custom = check_resp(requests.post(f"{BASE_URL}/values/", json={"field_id": f_color["id"], "value": "Custom"}), "Val Custom")

    # 5. Crea Regole (Rules)
    log("Creating Rules...")

    # RULE A (Availability): "V8 Biturbo" disponibile SOLO SE Modello == "GT Sport"
    requests.post(f"{BASE_URL}/rules/", json={
        "entity_version_id": v_id,
        "target_field_id": f_engine["id"],
        "target_value_id": v_v8["id"], # Target: V8
        "rule_type": "availability",
        "conditions": {
            "criteria": [
                {"field_id": f_model["id"], "operator": "EQUALS", "value": "GT Sport"}
            ]
        }
    })

    # RULE B (Availability): "Rosso Ferrari" disponibile SOLO SE Modello == "GT Sport"
    requests.post(f"{BASE_URL}/rules/", json={
        "entity_version_id": v_id,
        "target_field_id": f_color["id"],
        "target_value_id": v_red["id"], # Target: Rosso
        "rule_type": "availability",
        "conditions": {
            "criteria": [
                {"field_id": f_model["id"], "operator": "EQUALS", "value": "GT Sport"}
            ]
        }
    })

    # RULE C (Visibility): Campo "Codice RAL" visibile SOLO SE Colore == "Custom"
    requests.post(f"{BASE_URL}/rules/", json={
        "entity_version_id": v_id,
        "target_field_id": f_ral["id"],
        "target_value_id": None, # Target: Intero Campo
        "rule_type": "visibility",
        "conditions": {
            "criteria": [
                {"field_id": f_color["id"], "operator": "EQUALS", "value": "Custom"}
            ]
        }
    })

    log("Rules Created.")

    # 6. Publish
    log("Publishing Version...")
    requests.post(f"{BASE_URL}/versions/{v_id}/publish")

    print("\n--- DONE! ---")
    print(f"Entity ID: {entity_id}")
    print(f"Published Version ID: {v_id}")
    print("Now you can test POST /engine/calculate")

if __name__ == "__main__":
    run_seed()