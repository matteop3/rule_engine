import requests
import sys
import json

BASE_URL = "http://localhost:8000"

def log(msg):
    print(f"[TEST] {msg}")

def fail(msg):
    print(f"[ERROR] {msg}")
    sys.exit(1)

def run_test():
    log("--- INIZIO TEST CONFIGURAZIONI ---")

    # 1. SETUP: Cerchiamo l'Entità specifica creata dal seed
    resp = requests.get(f"{BASE_URL}/entities/")
    entities = resp.json()
    
    # Cerchiamo l'entità per NOME, così siamo sicuri di prendere quella giusta
    target_entity = next((e for e in entities if e['name'] == "Auto Sportiva"), None)
    
    if not target_entity:
        # Fallback: Se non c'è "Auto Sportiva", prendiamo la prima disponibile
        if len(entities) > 0:
            target_entity = entities[0]
            log(f"⚠️ 'Auto Sportiva' non trovata. Provo con l'entità: {target_entity['name']}")
        else:
            fail("Nessuna entità trovata nel DB. Esegui 'python seed_data.py' prima del test.")
            return # Serve per placare il linter di VS Code

    entity_id = target_entity['id']
    log(f"Usiamo Entity ID: {entity_id} ({target_entity['name']})")

    # Troviamo la versione Published
    resp = requests.get(f"{BASE_URL}/versions/?entity_id={entity_id}")
    versions = resp.json()
    
    # Cerchiamo lo status PUBLISHED
    pub_version = next((v for v in versions if v['status'] == 'PUBLISHED'), None)
    
    if pub_version is None:
        fail(f"L'entità {target_entity['name']} non ha nessuna versione PUBLISHED.")
        return

    v_id = pub_version['id']
    log(f"Usiamo Version ID: {v_id} (Published)")

    # ---------------------------------------------------------
    # STEP 1: CREATE (POST)
    # Simuliamo un utente che ha scelto "GT Sport" e motore "V8"
    # ---------------------------------------------------------
    log("\n1. CREAZIONE CONFIGURAZIONE (POST)...")
    payload = {
        "entity_version_id": v_id,
        "name": "La mia Supercar Rossa",
        "data": [
            {"field_id": 1, "value": "GT Sport"},  # Questo dovrebbe sbloccare il V8
            {"field_id": 2, "value": "V8 Biturbo"}
        ]
    }
    resp = requests.post(f"{BASE_URL}/configurations/", json=payload)
    if resp.status_code != 201:
        fail(f"Creazione fallita: {resp.text}")
    
    config = resp.json()
    config_id = config['id'] # Questo è l'UUID
    log(f"✅ Configurazione creata! UUID: {config_id}")

    # ---------------------------------------------------------
    # STEP 2: READ (GET /{id})
    # ---------------------------------------------------------
    log("\n2. LETTURA CONFIGURAZIONE (GET ID)...")
    resp = requests.get(f"{BASE_URL}/configurations/{config_id}")
    if resp.status_code != 200:
        fail("Lettura fallita")
    
    data = resp.json()
    if data['name'] != "La mia Supercar Rossa":
        fail("Nome non corrispondente")
    log(f"✅ Lettura OK. Dati salvati: {len(data['data'])} campi.")

    # ---------------------------------------------------------
    # STEP 3: LIST (GET /?filter)
    # ---------------------------------------------------------
    log("\n3. LISTA CONFIGURAZIONI (GET LIST)...")
    resp = requests.get(f"{BASE_URL}/configurations/?entity_version_id={v_id}")
    if resp.status_code != 200:
        fail("Lista fallita")
    
    configs_list = resp.json()
    found = any(c['id'] == config_id for c in configs_list)
    if not found:
        fail("La configurazione appena creata non appare nella lista.")
    log(f"✅ Lista OK. Trovate {len(configs_list)} configurazioni per questa versione.")

    # ---------------------------------------------------------
    # STEP 4: UPDATE (PATCH)
    # Cambiamo nome e aggiungiamo un colore
    # ---------------------------------------------------------
    log("\n4. AGGIORNAMENTO (PATCH)...")
    patch_payload = {
        "name": "La mia Supercar FINAL",
        "data": [
            {"field_id": 1, "value": "GT Sport"},
            {"field_id": 2, "value": "V8 Biturbo"},
            {"field_id": 3, "value": "Rosso Ferrari"} # Aggiungiamo input
        ]
    }
    resp = requests.patch(f"{BASE_URL}/configurations/{config_id}", json=patch_payload)
    if resp.status_code != 200:
        fail(f"Update fallito: {resp.text}")
    
    updated_config = resp.json()
    if updated_config['name'] != "La mia Supercar FINAL":
        fail("Il nome non è stato aggiornato")
    log("✅ Update OK. Nome e Dati aggiornati.")

    # ---------------------------------------------------------
    # STEP 5: RE-HYDRATION (CALCULATE)
    # Qui avviene la magia: il motore deve girare
    # ---------------------------------------------------------
    log("\n5. RE-HYDRATION (CALCULATE)...")
    resp = requests.get(f"{BASE_URL}/configurations/{config_id}/calculate")
    if resp.status_code != 200:
        fail(f"Calcolo fallito: {resp.text}")
    
    engine_result = resp.json()
    
    # Verifica logica: Poiché abbiamo scelto "GT Sport", il motore V8 deve essere disponibile
    fields_out = engine_result['fields']
    
    # Cerchiamo il campo Motore (assumiamo sia ID 2 dallo script seed)
    motor_field = next((f for f in fields_out if f['field_id'] == 2), None)
    
    if not motor_field:
        fail("Campo motore non trovato nel calcolo.")
        return
    
    # Verifichiamo che il valore corrente sia V8 (quindi input applicato)
    if motor_field['current_value'] != "V8 Biturbo":
        fail(f"Il motore non ha caricato il valore salvato. Valore attuale: {motor_field['current_value']}")
    
    log("✅ Re-hydration OK! Il motore ha processato gli input salvati.")

    # ---------------------------------------------------------
    # STEP 6: DELETE
    # ---------------------------------------------------------
    log("\n6. CANCELLAZIONE (DELETE)...")
    resp = requests.delete(f"{BASE_URL}/configurations/{config_id}")
    if resp.status_code != 204:
        fail("Delete fallita")
    
    # Verifica che non esista più
    resp = requests.get(f"{BASE_URL}/configurations/{config_id}")
    if resp.status_code != 404:
        fail("La configurazione esiste ancora dopo la delete!")
    
    log("✅ Cancellazione OK.")

    log("\n--- TEST COMPLETATO CON SUCCESSO! 🚀 ---")

if __name__ == "__main__":
    run_test()