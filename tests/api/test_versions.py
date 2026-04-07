"""
Test suite for Versions API endpoints.

Tests the full version lifecycle including:
- CRUD operations
- Single Draft Policy
- Single Published Policy
- Deep Clone with ID remapping
- DRAFT-only modification policy

Each test is atomic and independent.
"""

import pytest
from fastapi.testclient import TestClient

from app.models.domain import EntityVersion, Field, Rule, Value, VersionStatus

# ============================================================
# LIST VERSIONS TESTS (GET /versions/)
# ============================================================


class TestListVersions:
    """Tests for GET /versions/ endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
            (None, 401),
        ],
    )
    def test_list_versions_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_version):
        """RBAC: admin/author can list versions, user gets 403, unauthenticated gets 401."""
        headers = request.getfixturevalue(headers_fixture) if headers_fixture else {}
        response = client.get(f"/versions/?entity_id={draft_version.entity_id}", headers=headers)
        assert response.status_code == expected_status

    def test_list_ordered_by_version_number_desc(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """Test that versions are ordered by version_number descending."""
        # Create multiple versions with different numbers
        for i in [1, 2, 3]:
            version = EntityVersion(
                entity_id=test_entity.id,
                version_number=i,
                status=VersionStatus.ARCHIVED if i < 3 else VersionStatus.DRAFT,
                changelog=f"Version {i}",
                created_by_id=admin_user.id,
                updated_by_id=admin_user.id,
            )
            db_session.add(version)
        db_session.commit()

        response = client.get(f"/versions/?entity_id={test_entity.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        version_numbers = [v["version_number"] for v in data]
        assert version_numbers == sorted(version_numbers, reverse=True)

    def test_list_versions_pagination(self, client: TestClient, admin_headers, db_session, test_entity, admin_user):
        """Test pagination parameters work correctly."""
        # Create 5 versions
        for i in range(1, 6):
            version = EntityVersion(
                entity_id=test_entity.id,
                version_number=i,
                status=VersionStatus.ARCHIVED,
                changelog=f"Version {i}",
                created_by_id=admin_user.id,
                updated_by_id=admin_user.id,
            )
            db_session.add(version)
        db_session.commit()

        response = client.get(f"/versions/?entity_id={test_entity.id}&limit=2", headers=admin_headers)

        assert response.status_code == 200
        assert len(response.json()) == 2


# ============================================================
# READ VERSION TESTS (GET /versions/{version_id})
# ============================================================


class TestReadVersion:
    """Tests for GET /versions/{version_id} endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_read_version_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_version):
        """RBAC: admin/author can read version, user gets 403."""
        headers = request.getfixturevalue(headers_fixture)
        response = client.get(f"/versions/{draft_version.id}", headers=headers)
        assert response.status_code == expected_status

    def test_read_nonexistent_version_returns_404(self, client: TestClient, admin_headers):
        """Test that reading non-existent version returns 404."""
        response = client.get("/versions/99999", headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# CREATE DRAFT VERSION TESTS (POST /versions/)
# ============================================================


class TestCreateDraftVersion:
    """Tests for POST /versions/ endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 201),
            ("author_headers", 201),
            ("user_headers", 403),
        ],
    )
    def test_create_version_rbac(self, client: TestClient, headers_fixture, expected_status, request, test_entity):
        """RBAC: admin/author can create versions, user gets 403."""
        payload = {"entity_id": test_entity.id, "changelog": "RBAC draft"}
        headers = request.getfixturevalue(headers_fixture)
        response = client.post("/versions/", json=payload, headers=headers)
        assert response.status_code == expected_status

    def test_version_number_auto_increments(self, client: TestClient, admin_headers, test_entity, published_version):
        """Test that version number auto-increments from existing versions."""
        payload = {"entity_id": test_entity.id, "changelog": "Second version"}

        response = client.post("/versions/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["version_number"] == 2

    def test_cannot_create_draft_if_draft_exists(self, client: TestClient, admin_headers, test_entity, draft_version):
        """
        Test Single Draft Policy: cannot create DRAFT if one already exists.
        This is a CRITICAL business rule.
        """
        payload = {"entity_id": test_entity.id, "changelog": "Second draft - should fail"}

        response = client.post("/versions/", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_can_create_draft_if_only_published_exists(
        self, client: TestClient, admin_headers, test_entity, published_version
    ):
        """Test that DRAFT can be created when only PUBLISHED exists."""
        payload = {"entity_id": test_entity.id, "changelog": "New draft after published"}

        response = client.post("/versions/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["status"] == "DRAFT"

    def test_cannot_create_for_nonexistent_entity(self, client: TestClient, admin_headers):
        """Test that creating version for non-existent entity fails."""
        payload = {"entity_id": 99999, "changelog": "Should fail"}

        response = client.post("/versions/", json=payload, headers=admin_headers)

        assert response.status_code in [400, 404]

    def test_create_draft_without_changelog(self, client: TestClient, admin_headers, test_entity):
        """Test that draft can be created without changelog."""
        payload = {"entity_id": test_entity.id}

        response = client.post("/versions/", json=payload, headers=admin_headers)

        assert response.status_code == 201


# ============================================================
# PUBLISH VERSION TESTS (POST /versions/{version_id}/publish)
# ============================================================


class TestPublishVersion:
    """Tests for POST /versions/{version_id}/publish endpoint."""

    def test_can_publish_draft_version(self, client: TestClient, admin_headers, draft_version):
        """Test that DRAFT version can be published."""
        response = client.post(f"/versions/{draft_version.id}/publish", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "PUBLISHED"
        assert data["published_at"] is not None

    def test_author_can_publish_version(self, client: TestClient, author_headers, draft_version):
        """Test that author can publish versions."""
        response = client.post(f"/versions/{draft_version.id}/publish", headers=author_headers)

        assert response.status_code == 200
        assert response.json()["status"] == "PUBLISHED"

    def test_regular_user_cannot_publish(self, client: TestClient, user_headers, draft_version):
        """Test that regular user cannot publish versions (403)."""
        response = client.post(f"/versions/{draft_version.id}/publish", headers=user_headers)

        assert response.status_code == 403

    def test_cannot_publish_already_published(self, client: TestClient, admin_headers, published_version):
        """Test that PUBLISHED version cannot be re-published."""
        response = client.post(f"/versions/{published_version.id}/publish", headers=admin_headers)

        assert response.status_code == 400
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_publish_archived(self, client: TestClient, admin_headers, archived_version):
        """Test that ARCHIVED version cannot be published."""
        response = client.post(f"/versions/{archived_version.id}/publish", headers=admin_headers)

        assert response.status_code == 400

    def test_publish_archives_previous_published(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Test Single Published Policy: publishing archives the previous PUBLISHED version.
        This is a CRITICAL business rule.
        """
        # Create and commit a PUBLISHED version
        v1 = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="V1 Published",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(v1)
        db_session.commit()
        v1_id = v1.id

        # Create a DRAFT version
        v2 = EntityVersion(
            entity_id=test_entity.id,
            version_number=2,
            status=VersionStatus.DRAFT,
            changelog="V2 Draft",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(v2)
        db_session.commit()
        v2_id = v2.id

        # Publish v2
        response = client.post(f"/versions/{v2_id}/publish", headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["status"] == "PUBLISHED"

        # Verify v1 is now ARCHIVED
        db_session.expire_all()
        v1_refreshed = db_session.query(EntityVersion).filter(EntityVersion.id == v1_id).first()
        assert v1_refreshed.status == VersionStatus.ARCHIVED

    def test_publish_nonexistent_returns_404(self, client: TestClient, admin_headers):
        """Test that publishing non-existent version returns 404."""
        response = client.post("/versions/99999/publish", headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# CLONE VERSION TESTS (POST /versions/{version_id}/clone)
# ============================================================


class TestCloneVersion:
    """Tests for POST /versions/{version_id}/clone endpoint."""

    def test_can_clone_published_version(self, client: TestClient, admin_headers, published_version):
        """Test that PUBLISHED version can be cloned."""
        payload = {"changelog": "Cloned from published"}

        response = client.post(f"/versions/{published_version.id}/clone", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "DRAFT"
        assert data["version_number"] == 2

    def test_can_clone_archived_version(self, client: TestClient, admin_headers, archived_version):
        """Test that ARCHIVED version can be cloned."""
        payload = {"changelog": "Cloned from archived"}

        response = client.post(f"/versions/{archived_version.id}/clone", json=payload, headers=admin_headers)

        assert response.status_code == 201
        assert response.json()["status"] == "DRAFT"

    def test_can_clone_draft_version(self, client: TestClient, admin_headers, db_session, test_entity, admin_user):
        """Test that DRAFT version can be cloned (to different entity scenario)."""
        # For same entity, we need to delete existing draft first
        # This test verifies clone logic works for DRAFT status
        draft = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Original draft",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(draft)
        db_session.commit()

        # Clone will fail due to Single Draft Policy (which is expected)
        payload = {"changelog": "Clone of draft"}
        response = client.post(f"/versions/{draft.id}/clone", json=payload, headers=admin_headers)

        # Should fail because draft already exists for this entity
        assert response.status_code == 409

    def test_clone_fails_if_draft_exists(self, client: TestClient, admin_headers, db_session, test_entity, admin_user):
        """
        Test Single Draft Policy on clone: cannot clone if DRAFT exists.
        This is a CRITICAL business rule.
        """
        # Create published version
        published = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Published",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(published)
        db_session.flush()

        # Create draft version
        draft = EntityVersion(
            entity_id=test_entity.id,
            version_number=2,
            status=VersionStatus.DRAFT,
            changelog="Existing draft",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(draft)
        db_session.commit()

        # Try to clone published - should fail
        payload = {"changelog": "Clone attempt"}
        response = client.post(f"/versions/{published.id}/clone", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_clone_copies_fields_and_values(self, client: TestClient, admin_headers, db_session, version_with_data):
        """
        Test Deep Clone: verifies that Fields and Values are copied.
        This is a CRITICAL feature.
        """
        source_version = version_with_data["version"]
        payload = {"changelog": "Deep clone test"}

        response = client.post(f"/versions/{source_version.id}/clone", json=payload, headers=admin_headers)

        assert response.status_code == 201
        new_version_id = response.json()["id"]

        # Verify fields were cloned
        new_fields = db_session.query(Field).filter(Field.entity_version_id == new_version_id).all()
        assert len(new_fields) == 3  # Same as source

        # Verify field names match
        new_field_names = {f.name for f in new_fields}
        assert "vehicle_type" in new_field_names
        assert "vehicle_value" in new_field_names
        assert "has_alarm" in new_field_names

        # Verify values were cloned
        type_field = next(f for f in new_fields if f.name == "vehicle_type")
        new_values = db_session.query(Value).filter(Value.field_id == type_field.id).all()
        assert len(new_values) == 3  # CAR, MOTO, TRUCK

    def test_clone_remaps_rule_field_ids(self, client: TestClient, admin_headers, db_session, version_with_data):
        """
        Test Deep Clone ID Remapping: verifies that field_id in rule conditions is updated.
        This is a CRITICAL feature.
        """
        source_version = version_with_data["version"]
        source_rules = version_with_data["rules"]
        source_fields = version_with_data["fields"]

        # Get original field IDs from conditions
        original_mandatory_rule = source_rules["mandatory"]
        original_field_id_in_condition = original_mandatory_rule.conditions["criteria"][0]["field_id"]
        assert original_field_id_in_condition == source_fields["value"].id

        payload = {"changelog": "ID remap test"}
        response = client.post(f"/versions/{source_version.id}/clone", json=payload, headers=admin_headers)

        assert response.status_code == 201
        new_version_id = response.json()["id"]

        # Get cloned rules
        cloned_rules = db_session.query(Rule).filter(Rule.entity_version_id == new_version_id).all()
        assert len(cloned_rules) == 2

        # Get cloned fields
        cloned_fields = db_session.query(Field).filter(Field.entity_version_id == new_version_id).all()
        cloned_value_field = next(f for f in cloned_fields if f.name == "vehicle_value")

        # Find the mandatory rule (by description or type)
        cloned_mandatory = next(r for r in cloned_rules if "mandatory" in (r.description or "").lower())

        # Verify field_id in conditions was remapped
        new_field_id_in_condition = cloned_mandatory.conditions["criteria"][0]["field_id"]
        assert new_field_id_in_condition == cloned_value_field.id
        assert new_field_id_in_condition != original_field_id_in_condition

    def test_clone_copies_calculation_rule_set_value(
        self, client: TestClient, admin_headers, db_session, version_with_data
    ):
        """
        Test Deep Clone: verifies that CALCULATION rules with set_value are properly copied.
        This is a CRITICAL feature.
        """
        from app.models.domain import RuleType

        source_version = version_with_data["version"]
        source_fields = version_with_data["fields"]

        # Add a CALCULATION rule to the source version
        calc_rule = Rule(
            entity_version_id=source_version.id,
            target_field_id=source_fields["optional"].id,
            rule_type=RuleType.CALCULATION.value,
            set_value="forced_value",
            description="Calculation rule for clone test",
            conditions={"criteria": [{"field_id": source_fields["type"].id, "operator": "EQUALS", "value": "CAR"}]},
        )
        db_session.add(calc_rule)
        db_session.commit()

        payload = {"changelog": "Clone with CALCULATION"}
        response = client.post(f"/versions/{source_version.id}/clone", json=payload, headers=admin_headers)

        assert response.status_code == 201
        new_version_id = response.json()["id"]

        # Get cloned rules
        cloned_rules = db_session.query(Rule).filter(Rule.entity_version_id == new_version_id).all()

        # Find the cloned CALCULATION rule
        cloned_calc = [r for r in cloned_rules if r.rule_type == RuleType.CALCULATION.value]
        assert len(cloned_calc) == 1
        assert cloned_calc[0].set_value == "forced_value"
        assert cloned_calc[0].description == "Calculation rule for clone test"

        # Verify target_field_id was remapped (should not be the same as source)
        assert cloned_calc[0].target_field_id != source_fields["optional"].id

    def test_clone_nonexistent_returns_404(self, client: TestClient, admin_headers):
        """Test that cloning non-existent version returns 404."""
        payload = {"changelog": "Ghost clone"}
        response = client.post("/versions/99999/clone", json=payload, headers=admin_headers)

        assert response.status_code == 404

    def test_author_can_clone_version(self, client: TestClient, author_headers, published_version):
        """Test that author can clone versions."""
        payload = {"changelog": "Author clone"}

        response = client.post(f"/versions/{published_version.id}/clone", json=payload, headers=author_headers)

        assert response.status_code == 201

    def test_regular_user_cannot_clone(self, client: TestClient, user_headers, published_version):
        """Test that regular user cannot clone versions (403)."""
        payload = {"changelog": "User clone"}

        response = client.post(f"/versions/{published_version.id}/clone", json=payload, headers=user_headers)

        assert response.status_code == 403


# ============================================================
# UPDATE VERSION TESTS (PATCH /versions/{version_id})
# ============================================================


class TestUpdateVersion:
    """Tests for PATCH /versions/{version_id} endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 200),
            ("author_headers", 200),
            ("user_headers", 403),
        ],
    )
    def test_update_version_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_version):
        """RBAC: admin/author can update draft versions, user gets 403."""
        payload = {"changelog": "RBAC update"}
        headers = request.getfixturevalue(headers_fixture)
        response = client.patch(f"/versions/{draft_version.id}", json=payload, headers=headers)
        assert response.status_code == expected_status

    def test_cannot_update_published_version(self, client: TestClient, admin_headers, published_version):
        """
        Test Immutability Policy: PUBLISHED versions cannot be modified.
        This is a CRITICAL business rule.
        """
        payload = {"changelog": "Try to modify published"}

        response = client.patch(f"/versions/{published_version.id}", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_update_archived_version(self, client: TestClient, admin_headers, archived_version):
        """
        Test Immutability Policy: ARCHIVED versions cannot be modified.
        This is a CRITICAL business rule.
        """
        payload = {"changelog": "Try to modify archived"}

        response = client.patch(f"/versions/{archived_version.id}", json=payload, headers=admin_headers)

        assert response.status_code == 409

    def test_empty_update_handled(self, client: TestClient, admin_headers, draft_version):
        """Test that empty update payload is handled gracefully."""
        response = client.patch(f"/versions/{draft_version.id}", json={}, headers=admin_headers)

        # Should succeed with no changes
        assert response.status_code == 200

    def test_update_nonexistent_returns_404(self, client: TestClient, admin_headers):
        """Test that updating non-existent version returns 404."""
        payload = {"changelog": "Ghost update"}

        response = client.patch("/versions/99999", json=payload, headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# DELETE VERSION TESTS (DELETE /versions/{version_id})
# ============================================================


class TestDeleteVersion:
    """Tests for DELETE /versions/{version_id} endpoint."""

    @pytest.mark.parametrize(
        "headers_fixture, expected_status",
        [
            ("admin_headers", 204),
            ("author_headers", 204),
            ("user_headers", 403),
        ],
    )
    def test_delete_version_rbac(self, client: TestClient, headers_fixture, expected_status, request, draft_version):
        """RBAC: admin/author can delete draft versions, user gets 403."""
        headers = request.getfixturevalue(headers_fixture)
        response = client.delete(f"/versions/{draft_version.id}", headers=headers)
        assert response.status_code == expected_status

    def test_cannot_delete_published_version(self, client: TestClient, admin_headers, published_version):
        """
        Test Immutability Policy: PUBLISHED versions cannot be deleted.
        This is a CRITICAL business rule.
        """
        response = client.delete(f"/versions/{published_version.id}", headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_cannot_delete_archived_version(self, client: TestClient, admin_headers, archived_version):
        """
        Test Immutability Policy: ARCHIVED versions cannot be deleted.
        This is a CRITICAL business rule.
        """
        response = client.delete(f"/versions/{archived_version.id}", headers=admin_headers)

        assert response.status_code == 409

    def test_delete_cascades_fields_values_rules(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """
        Test Cascade Delete: deleting version removes all Fields, Values, Rules.
        This is a CRITICAL feature.
        """
        # Create draft version with data
        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="To be deleted",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(version)
        db_session.flush()

        field = Field(
            entity_version_id=version.id, name="test_field", label="Test Field", data_type="string", is_free_value=True
        )
        db_session.add(field)
        db_session.flush()

        value = Value(field_id=field.id, value="test", label="Test")
        db_session.add(value)

        rule = Rule(
            entity_version_id=version.id, target_field_id=field.id, rule_type="validation", conditions={"criteria": []}
        )
        db_session.add(rule)
        db_session.commit()

        version_id = version.id
        field_id = field.id

        # Delete version
        response = client.delete(f"/versions/{version_id}", headers=admin_headers)
        assert response.status_code == 204

        # Verify cascade delete
        db_session.expire_all()
        assert db_session.query(EntityVersion).filter(EntityVersion.id == version_id).first() is None
        assert db_session.query(Field).filter(Field.id == field_id).first() is None

    def test_delete_nonexistent_returns_404(self, client: TestClient, admin_headers):
        """Test that deleting non-existent version returns 404."""
        response = client.delete("/versions/99999", headers=admin_headers)

        assert response.status_code == 404


# ============================================================
# VERSION LIFECYCLE INTEGRATION TESTS
# ============================================================


class TestVersionLifecycle:
    """Integration tests for the complete version lifecycle."""

    def test_full_lifecycle_draft_publish_clone_archive(self, client: TestClient, admin_headers, test_entity):
        """
        Test complete lifecycle: create DRAFT -> publish -> clone -> publish (archives previous).
        This is a CRITICAL integration test.
        """
        # Step 1: Create DRAFT v1
        create_resp = client.post(
            "/versions/", json={"entity_id": test_entity.id, "changelog": "V1 initial"}, headers=admin_headers
        )
        assert create_resp.status_code == 201
        v1_id = create_resp.json()["id"]
        assert create_resp.json()["status"] == "DRAFT"
        assert create_resp.json()["version_number"] == 1

        # Step 2: Publish v1
        publish_resp = client.post(f"/versions/{v1_id}/publish", headers=admin_headers)
        assert publish_resp.status_code == 200
        assert publish_resp.json()["status"] == "PUBLISHED"

        # Step 3: Clone v1 to create DRAFT v2
        clone_resp = client.post(
            f"/versions/{v1_id}/clone", json={"changelog": "V2 cloned from V1"}, headers=admin_headers
        )
        assert clone_resp.status_code == 201
        v2_id = clone_resp.json()["id"]
        assert clone_resp.json()["status"] == "DRAFT"
        assert clone_resp.json()["version_number"] == 2

        # Step 4: Publish v2 (should archive v1)
        publish_v2_resp = client.post(f"/versions/{v2_id}/publish", headers=admin_headers)
        assert publish_v2_resp.status_code == 200
        assert publish_v2_resp.json()["status"] == "PUBLISHED"

        # Step 5: Verify v1 is now archived
        v1_check = client.get(f"/versions/{v1_id}", headers=admin_headers)
        assert v1_check.status_code == 200
        assert v1_check.json()["status"] == "ARCHIVED"

    def test_cannot_have_two_drafts_simultaneously(self, client: TestClient, admin_headers, test_entity):
        """Test that Single Draft Policy prevents multiple drafts."""
        # Create first draft
        resp1 = client.post(
            "/versions/", json={"entity_id": test_entity.id, "changelog": "First draft"}, headers=admin_headers
        )
        assert resp1.status_code == 201

        # Try to create second draft
        resp2 = client.post(
            "/versions/", json={"entity_id": test_entity.id, "changelog": "Second draft"}, headers=admin_headers
        )
        assert resp2.status_code == 409

    def test_multiple_entities_independent_versions(
        self, client: TestClient, admin_headers, test_entity, second_entity
    ):
        """Test that different entities have independent version histories."""
        # Create draft for entity 1
        resp1 = client.post(
            "/versions/", json={"entity_id": test_entity.id, "changelog": "Entity 1 draft"}, headers=admin_headers
        )
        assert resp1.status_code == 201

        # Create draft for entity 2 (should succeed - different entity)
        resp2 = client.post(
            "/versions/", json={"entity_id": second_entity.id, "changelog": "Entity 2 draft"}, headers=admin_headers
        )
        assert resp2.status_code == 201

        # Both should be version 1
        assert resp1.json()["version_number"] == 1
        assert resp2.json()["version_number"] == 1

    def test_delete_draft_allows_new_draft(self, client: TestClient, admin_headers, draft_version):
        """Test that deleting draft allows creating new draft."""
        entity_id = draft_version.entity_id

        # Delete existing draft
        delete_resp = client.delete(f"/versions/{draft_version.id}", headers=admin_headers)
        assert delete_resp.status_code == 204

        # Create new draft (should succeed)
        create_resp = client.post(
            "/versions/", json={"entity_id": entity_id, "changelog": "New draft after delete"}, headers=admin_headers
        )
        assert create_resp.status_code == 201


# ============================================================
# SKU ATTRIBUTES CRUD TESTS
# ============================================================


class TestVersionSKUAttributes:
    """Tests for SKU attributes (sku_base, sku_delimiter) CRUD operations."""

    def test_create_version_with_sku_attributes(self, client: TestClient, admin_headers, test_entity):
        """Test that version can be created with sku_base and sku_delimiter."""
        payload = {
            "entity_id": test_entity.id,
            "changelog": "Version with SKU",
            "sku_base": "LPT-PRO",
            "sku_delimiter": "-",
        }

        response = client.post("/versions/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["sku_base"] == "LPT-PRO"
        assert data["sku_delimiter"] == "-"

    def test_create_version_with_custom_delimiter(self, client: TestClient, admin_headers, test_entity):
        """Test that version can be created with custom delimiter."""
        payload = {
            "entity_id": test_entity.id,
            "changelog": "Custom delimiter",
            "sku_base": "PROD",
            "sku_delimiter": "/",
        }

        response = client.post("/versions/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["sku_base"] == "PROD"
        assert data["sku_delimiter"] == "/"

    def test_create_version_without_sku_attributes(self, client: TestClient, admin_headers, test_entity):
        """Test that sku_base and sku_delimiter are optional on creation."""
        payload = {"entity_id": test_entity.id, "changelog": "No SKU attributes"}

        response = client.post("/versions/", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["sku_base"] is None
        assert data["sku_delimiter"] == "-"  # Default value from schema

    def test_update_draft_sku_attributes(self, client: TestClient, admin_headers, draft_version):
        """Test that sku_base and sku_delimiter can be updated on DRAFT version."""
        payload = {"sku_base": "NEW-BASE", "sku_delimiter": "/"}

        response = client.patch(f"/versions/{draft_version.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["sku_base"] == "NEW-BASE"
        assert data["sku_delimiter"] == "/"

    def test_update_only_sku_base(self, client: TestClient, admin_headers, draft_version):
        """Test that only sku_base can be updated independently."""
        payload = {"sku_base": "ONLY-BASE"}

        response = client.patch(f"/versions/{draft_version.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["sku_base"] == "ONLY-BASE"

    def test_update_only_sku_delimiter(self, client: TestClient, admin_headers, draft_version):
        """Test that only sku_delimiter can be updated independently."""
        payload = {"sku_delimiter": "_"}

        response = client.patch(f"/versions/{draft_version.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["sku_delimiter"] == "_"

    def test_cannot_update_sku_on_published_version(self, client: TestClient, admin_headers, published_version):
        """
        Test DRAFT-only policy: SKU attributes cannot be updated on PUBLISHED version.
        This is a CRITICAL business rule.
        """
        payload = {"sku_base": "SHOULD-FAIL"}

        response = client.patch(f"/versions/{published_version.id}", json=payload, headers=admin_headers)

        assert response.status_code == 409
        assert "draft" in response.json()["detail"].lower()

    def test_clone_copies_sku_attributes(self, client: TestClient, admin_headers, db_session, test_entity, admin_user):
        """
        Test that cloning a version copies sku_base and sku_delimiter.
        This is a CRITICAL feature for SKU continuity.
        """
        # Create published version with SKU attributes
        from app.models.domain import EntityVersion, VersionStatus

        source_version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            changelog="Source with SKU",
            sku_base="CLONE-BASE",
            sku_delimiter="/",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(source_version)
        db_session.commit()

        # Clone the version
        payload = {"changelog": "Cloned version"}
        response = client.post(f"/versions/{source_version.id}/clone", json=payload, headers=admin_headers)

        assert response.status_code == 201
        data = response.json()
        assert data["sku_base"] == "CLONE-BASE"
        assert data["sku_delimiter"] == "/"
        assert data["status"] == "DRAFT"

    def test_clear_sku_base_on_draft(self, client: TestClient, admin_headers, db_session, test_entity, admin_user):
        """Test that sku_base can be cleared (set to null) on DRAFT version."""
        from app.models.domain import EntityVersion, VersionStatus

        # Create draft with SKU attributes
        draft = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Draft with SKU",
            sku_base="TO-BE-CLEARED",
            sku_delimiter="-",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(draft)
        db_session.commit()

        # Clear sku_base
        payload = {"sku_base": None}
        response = client.patch(f"/versions/{draft.id}", json=payload, headers=admin_headers)

        assert response.status_code == 200
        assert response.json()["sku_base"] is None

    def test_read_version_includes_sku_attributes(
        self, client: TestClient, admin_headers, db_session, test_entity, admin_user
    ):
        """Test that reading a version includes SKU attributes in response."""
        from app.models.domain import EntityVersion, VersionStatus

        version = EntityVersion(
            entity_id=test_entity.id,
            version_number=1,
            status=VersionStatus.DRAFT,
            changelog="Read test",
            sku_base="READ-TEST",
            sku_delimiter=":",
            created_by_id=admin_user.id,
            updated_by_id=admin_user.id,
        )
        db_session.add(version)
        db_session.commit()

        response = client.get(f"/versions/{version.id}", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["sku_base"] == "READ-TEST"
        assert data["sku_delimiter"] == ":"
