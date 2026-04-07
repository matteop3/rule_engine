"""
Test suite for Entities API endpoints.

Tests the full CRUD lifecycle for Entity management.
Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import Entity

# ============================================================
# CREATE ENTITY TESTS (POST /entities/)
# ============================================================


class TestCreateEntity:
    """Tests for POST /entities/ endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 201),
            ("author_headers", 201),
            ("user_headers", 403),
            (None, 401),
        ],
    )
    def test_create_entity_rbac(self, client: TestClient, headers_fixture, expected_status, request):
        """RBAC: admin/author can create entities, user gets 403, unauthenticated gets 401."""
        payload = {"name": f"RBAC Entity {headers_fixture}", "description": "RBAC test"}
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.post("/entities/", json=payload, headers=headers)
        assert response.status_code == expected_status

    def test_cannot_create_duplicate_name(self, client: TestClient, admin_headers, test_entity):
        """Test that creating entity with existing name returns 400."""
        payload = {
            "name": "Test Entity",  # Same as test_entity fixture
            "description": "Duplicate",
        }

        response = client.post("/entities/", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_create_entity_without_description(self, client: TestClient, admin_headers):
        """Test that entity can be created without description."""
        payload = {"name": "No Description Entity"}

        response = client.post("/entities/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "No Description Entity"
        # Description should be None or empty
        assert data.get("description") is None or data.get("description") == ""

    def test_create_entity_empty_name_fails(self, client: TestClient, admin_headers):
        """Test that empty name returns validation error."""
        payload = {"name": "", "description": "Empty name"}

        response = client.post("/entities/", json=payload, headers=admin_headers)

        assert response.status_code == 422

    def test_create_entity_tracks_created_by(self, client: TestClient, admin_headers, admin_user):
        """Test that created_by is tracked correctly."""
        payload = {"name": "Tracked Entity", "description": "Track creator"}

        response = client.post("/entities/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data.get("created_by_id") == admin_user.id


# ============================================================
# LIST ENTITIES TESTS (GET /entities/)
# ============================================================


class TestListEntities:
    """Tests for GET /entities/ endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 200),
            (None, 401),
        ],
    )
    def test_list_entities_rbac(self, client: TestClient, headers_fixture, expected_status, request, test_entity):
        """RBAC: all authenticated roles can list entities, unauthenticated gets 401."""
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.get("/entities/", headers=headers)
        assert response.status_code == expected_status

    def test_list_entities_pagination_skip(self, client: TestClient, admin_headers, db_session, admin_user):
        """Test skip parameter works correctly."""
        # Create multiple entities
        for i in range(5):
            entity = Entity(
                name=f"Skip Test Entity {i}",
                description=f"Entity {i}",
                created_by_id=admin_user.id,
                updated_by_id=admin_user.id,
            )
            db_session.add(entity)
        db_session.commit()

        response_all = client.get("/entities/", headers=admin_headers)
        response_skip = client.get("/entities/?skip=2", headers=admin_headers)

        assert response_all.status_code == 200
        assert response_skip.status_code == 200
        assert len(response_skip.json()) == len(response_all.json()) - 2

    def test_list_entities_pagination_limit(self, client: TestClient, admin_headers, db_session, admin_user):
        """Test limit parameter works correctly."""
        # Create multiple entities
        for i in range(5):
            entity = Entity(
                name=f"Limit Test Entity {i}",
                description=f"Entity {i}",
                created_by_id=admin_user.id,
                updated_by_id=admin_user.id,
            )
            db_session.add(entity)
        db_session.commit()

        response = client.get("/entities/?limit=2", headers=admin_headers)

        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_entities_limit_over_100_rejected(self, client: TestClient, admin_headers, test_entity):
        """Test that limit > 100 is rejected with 422."""
        response = client.get("/entities/?limit=200", headers=admin_headers)

        assert response.status_code == 422


# ============================================================
# READ ENTITY TESTS (GET /entities/{entity_id})
# ============================================================


class TestReadEntity:
    """Tests for GET /entities/{entity_id} endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 200),
            (None, 401),
        ],
    )
    def test_read_entity_rbac(self, client: TestClient, headers_fixture, expected_status, request, test_entity):
        """RBAC: all authenticated roles can read entity, unauthenticated gets 401."""
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.get(f"/entities/{test_entity.id}", headers=headers)
        assert response.status_code == expected_status

    def test_read_nonexistent_entity_returns_404(self, client: TestClient, admin_headers):
        """Test that reading non-existent entity returns 404."""
        response = client.get("/entities/99999", headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# UPDATE ENTITY TESTS (PUT /entities/{entity_id})
# ============================================================


class TestUpdateEntity:
    """Tests for PUT /entities/{entity_id} endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
            (None, 401),
        ],
    )
    def test_update_entity_rbac(self, client: TestClient, headers_fixture, expected_status, request, test_entity):
        """RBAC: admin/author can update entities, user gets 403, unauthenticated gets 401."""
        payload = {"description": "RBAC updated"}
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.patch(f"/entities/{test_entity.id}", json=payload, headers=headers)
        assert response.status_code == expected_status

    def test_cannot_update_to_duplicate_name(self, client: TestClient, admin_headers, test_entity, second_entity):
        """Test that updating to existing name returns 400."""
        payload = {
            "name": "Second Entity",  # Already exists
            "description": "Trying to duplicate",
        }

        response = client.patch(f"/entities/{test_entity.id}", json=payload, headers=admin_headers)

        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_update_same_name_succeeds(self, client: TestClient, admin_headers, test_entity):
        """Test that updating entity with same name succeeds."""
        payload = {
            "name": "Test Entity",  # Same as current
            "description": "New description only",
        }

        response = client.patch(f"/entities/{test_entity.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["description"] == "New description only"

    def test_update_nonexistent_entity_returns_404(self, client: TestClient, admin_headers):
        """Test that updating non-existent entity returns 404."""
        payload = {"name": "Ghost Entity"}

        response = client.patch("/entities/99999", json=payload, headers=admin_headers)

        assert response.status_code == 404

    def test_update_tracks_updated_by(self, client: TestClient, author_headers, test_entity, author_user):
        """Test that updated_by is tracked correctly."""
        payload = {"name": "Track Update", "description": "Track updater"}

        response = client.patch(f"/entities/{test_entity.id}", json=payload, headers=author_headers)

        assert response.status_code == 200
        assert response.json().get("updated_by_id") == author_user.id


# ============================================================
# DELETE ENTITY TESTS (DELETE /entities/{entity_id})
# ============================================================


class TestDeleteEntity:
    """Tests for DELETE /entities/{entity_id} endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 204),
            ("author_headers", 204),
            ("user_headers", 403),
            (None, 401),
        ],
    )
    def test_delete_entity_rbac(self, client: TestClient, headers_fixture, expected_status, request, test_entity):
        """RBAC: admin/author can delete entities, user gets 403, unauthenticated gets 401."""
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.delete(f"/entities/{test_entity.id}", headers=headers)
        assert response.status_code == expected_status

    def test_cannot_delete_entity_with_versions(self, client: TestClient, admin_headers, test_entity, draft_version):
        """Test that entity with versions cannot be deleted (409)."""
        response = client.delete(f"/entities/{test_entity.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "versions" in response.json()["detail"].lower()

    def test_cannot_delete_entity_with_published_version(
        self, client: TestClient, admin_headers, test_entity, published_version
    ):
        """Test that entity with PUBLISHED version cannot be deleted (409)."""
        response = client.delete(f"/entities/{test_entity.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "versions" in response.json()["detail"].lower()

    def test_cannot_delete_entity_with_archived_version(
        self, client: TestClient, admin_headers, test_entity, archived_version
    ):
        """Test that entity with ARCHIVED version cannot be deleted (409)."""
        response = client.delete(f"/entities/{test_entity.id}", headers=admin_headers)

        assert response.status_code == 409

    def test_delete_nonexistent_entity_returns_404(self, client: TestClient, admin_headers):
        """Test that deleting non-existent entity returns 404."""
        response = client.delete("/entities/99999", headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# EDGE CASES
# ============================================================


class TestEntityEdgeCases:
    """Edge case and boundary tests for Entity API."""

    def test_entity_name_with_special_characters(self, client: TestClient, admin_headers):
        """Test that entity names with special characters are handled."""
        payload = {"name": "Entity-With_Special.Chars (v1)", "description": "Special chars test"}

        response = client.post("/entities/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["name"] == "Entity-With_Special.Chars (v1)"

    def test_entity_very_long_description(self, client: TestClient, admin_headers):
        """Test that long descriptions are handled."""
        payload = {
            "name": "Long Description Entity",
            "description": "A" * 1000,  # 1000 characters
        }

        response = client.post("/entities/", json=payload, headers=admin_headers)

        # Should either succeed or return validation error
        assert response.status_code in [201, 422]

    def test_list_empty_entities(self, client: TestClient, admin_headers):
        """Test listing when no entities exist."""
        response = client.get("/entities/", headers=admin_headers)

        assert response.status_code == 200
        assert response.json() == []

    def test_pagination_beyond_results(self, client: TestClient, admin_headers, test_entity):
        """Test pagination with skip beyond available results."""
        response = client.get("/entities/?skip=1000", headers=admin_headers)

        assert response.status_code == 200
        assert response.json() == []
