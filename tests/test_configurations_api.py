import pytest
from app.models.domain import Entity, EntityVersion, Field, User, UserRole, VersionStatus, FieldType
from app.core.security import create_access_token
from fastapi.testclient import TestClient

# --- FIXTURE PER AUTENTICAZIONE ---
@pytest.fixture(scope="function")
def auth_headers(db_session):
    """
    Crea un utente 'dummy' e genera un token JWT valido.
    Restituisce gli header HTTP pronti per l'uso.
    """
    # 1. Creiamo l'utente nel DB
    user = User(
        email="testuser@example.com",
        hashed_password="fakehash", # Non serve vera password, generiamo il token manualmente
        role=UserRole.USER,
        is_active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    # 2. Generiamo il token bypassando il login
    access_token = create_access_token(subject=user.id)
    
    return {"Authorization": f"Bearer {access_token}"}

# --- FIXTURE SCENARIO (DATI DINAMICI) ---
@pytest.fixture(scope="function")
def config_scenario(db_session):
    """
    Prepara un'entità, una versione e dei campi per testare il salvataggio.
    """
    # Entità e Versione
    entity = Entity(name="Config Test Entity", description="Test API")
    db_session.add(entity)
    db_session.commit()
    
    version = EntityVersion(entity_id=entity.id, version_number=1, status=VersionStatus.PUBLISHED)
    db_session.add(version)
    db_session.commit()

    # Campi
    f_model = Field(entity_version_id=version.id, name="model", label="Modello", data_type=FieldType.STRING.value, step=1, sequence=1, is_free_value=True)
    f_color = Field(entity_version_id=version.id, name="color", label="Colore", data_type=FieldType.STRING.value, step=1, sequence=2, is_free_value=True)
    
    db_session.add_all([f_model, f_color])
    db_session.commit()

    return {
        "v_id": version.id,
        "f_model_id": f_model.id,
        "f_color_id": f_color.id
    }

# --- IL TEST VERO E PROPRIO (RIFATTO) ---
def test_configuration_lifecycle(client: TestClient, db_session, auth_headers, config_scenario):
    """
    Testa il ciclo completo: CREATE -> READ -> LIST -> UPDATE -> CALCULATE -> DELETE.
    """
    ids = config_scenario
    
    # ---------------------------------------------------------
    # 1. CREATE (POST)
    # ---------------------------------------------------------
    payload = {
        "entity_version_id": ids["v_id"],
        "name": "Il mio Preventivo",
        "data": [
            {"field_id": ids["f_model_id"], "value": "Tesla Model S"},
            {"field_id": ids["f_color_id"], "value": "Red"}
        ]
    }
    
    # Nota: passiamo headers=auth_headers per simulare il login
    resp = client.post("/configurations/", json=payload, headers=auth_headers)
    assert resp.status_code == 201, f"Creazione fallita: {resp.text}"
    
    config_data = resp.json()
    config_id = config_data["id"]
    assert config_data["name"] == "Il mio Preventivo"
    assert len(config_data["data"]) == 2

   #print(f"\n[TEST] Config creata con ID: {config_id}")

    # ---------------------------------------------------------
    # 2. READ (GET /{id})
    # ---------------------------------------------------------
    resp = client.get(f"/configurations/{config_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == config_id

    # ---------------------------------------------------------
    # 3. LIST (GET /)
    # ---------------------------------------------------------
    resp = client.get(f"/configurations/?entity_version_id={ids['v_id']}", headers=auth_headers)
    assert resp.status_code == 200
    items = resp.json()
    # Verifichiamo che la nostra config sia nella lista
    assert any(c["id"] == config_id for c in items)

    # ---------------------------------------------------------
    # 4. UPDATE (PATCH) - Cambiamo nome e valore
    # ---------------------------------------------------------
    patch_payload = {
        "name": "Preventivo Aggiornato",
        "data": [
            {"field_id": ids["f_model_id"], "value": "Tesla Model X"}, # Cambiato modello
            {"field_id": ids["f_color_id"], "value": "Red"}
        ]
    }
    resp = client.patch(f"/configurations/{config_id}", json=patch_payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Preventivo Aggiornato"
    
    # Verifica che il dato sia cambiato nel DB
    resp = client.get(f"/configurations/{config_id}", headers=auth_headers)
    model_val = next(d["value"] for d in resp.json()["data"] if d["field_id"] == ids["f_model_id"])
    assert model_val == "Tesla Model X"

    # ---------------------------------------------------------
    # 5. RE-HYDRATION & CALCULATE (GET /{id}/calculate)
    # Questo è il punto critico: testiamo l'integrazione col Rule Engine
    # ---------------------------------------------------------
    resp = client.get(f"/configurations/{config_id}/calculate", headers=auth_headers)
    assert resp.status_code == 200
    
    engine_response = resp.json()
    # Cerchiamo il campo Model nell'output del motore
    field_out = next(f for f in engine_response["fields"] if f["field_id"] == ids["f_model_id"])
    
    # VERIFICA: Il motore deve aver ricevuto il valore "Tesla Model X" dal DB
    assert field_out["current_value"] == "Tesla Model X"
    assert field_out["is_hidden"] is False

    # ---------------------------------------------------------
    # 6. DELETE
    # ---------------------------------------------------------
    resp = client.delete(f"/configurations/{config_id}", headers=auth_headers)
    assert resp.status_code == 204

    # Verifica che sia sparito
    resp = client.get(f"/configurations/{config_id}", headers=auth_headers)
    assert resp.status_code == 404