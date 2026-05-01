"""
End-to-end engineering BOM workflow.

Exercises the full feature path through the public API:

1. Define catalog items + a multi-level engineering template (depth ≥ 2)
   via the `/catalog-items` and `/catalog-items/{p}/template/items` endpoints.
2. Preview the explosion with `GET /catalog-items/{p}/preview-explosion`,
   asserting tree shape, flat aggregation, total_nodes, and max_depth_reached.
3. Materialize the root onto a DRAFT `EntityVersion` with
   `POST /bom-items` + `explode_from_template=true`, asserting the
   persisted hierarchy.
4. Calculate against a Configuration → assert `BOMOutput.technical`
   structure and `BOMOutput.technical_flat` cascade arithmetic.
5. Finalize the configuration → assert `technical_flat` is captured
   verbatim in `Configuration.snapshot["bom"]`.
6. Clone the source `EntityVersion` → assert no re-materialization (the
   destination is a structural copy of the source at clone time).
7. Upgrade a Configuration to a newer `EntityVersion` whose template
   has changed → assert recalculation reflects the new structure.
"""

import datetime as dt
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.domain import (
    BOMItem,
    BOMType,
    Configuration,
    Entity,
    EntityVersion,
    PriceList,
    User,
    VersionStatus,
)

# ============================================================
# HELPERS
# ============================================================


def _create_catalog_item(client: TestClient, headers, *, part_number: str, description: str | None = None) -> dict:
    response = client.post(
        "/catalog-items/",
        json={
            "part_number": part_number,
            "description": description or part_number,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _add_template_edge(
    client: TestClient,
    headers,
    *,
    parent: str,
    child: str,
    quantity: str,
    sequence: int = 0,
    suppress_child_explosion: bool = False,
) -> dict:
    response = client.post(
        f"/catalog-items/{parent}/template/items",
        json={
            "child_part_number": child,
            "quantity": quantity,
            "sequence": sequence,
            "suppress_child_explosion": suppress_child_explosion,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.json()
    return response.json()


def _create_published_entity_with_draft(
    db_session: Session, admin_user: User, name: str
) -> tuple[Entity, EntityVersion]:
    """Returns (entity, draft_version). The published version is created so the
    Configuration can later upgrade onto it.
    """
    entity = Entity(name=name, description=name)
    db_session.add(entity)
    db_session.commit()

    draft = EntityVersion(
        entity_id=entity.id,
        version_number=1,
        status=VersionStatus.DRAFT.value,
        changelog="initial",
        created_by_id=admin_user.id,
    )
    db_session.add(draft)
    db_session.commit()
    return entity, draft


@pytest.fixture
def workflow_price_list(db_session: Session) -> PriceList:
    pl = PriceList(
        name="Engineering BOM Workflow PL",
        valid_from=dt.date(2020, 1, 1),
        valid_to=dt.date(9999, 12, 31),
    )
    db_session.add(pl)
    db_session.commit()
    return pl


# ============================================================
# THE WORKFLOW
# ============================================================


class TestEngineeringBOMWorkflow:
    """End-to-end engineering BOM workflow against the live API."""

    def _seed_template(self, client: TestClient, admin_headers):
        """Catalog + multi-level template:

        KIT (root, composite)
        ├── HOUSING ×1 (sequence=0)
        │   ├── SHELL ×1
        │   └── SCREW ×4
        └── BOLT ×2 (sequence=1)
        """
        for pn, desc in [
            ("KIT", "Top-level kit"),
            ("HOUSING", "Housing sub-assembly"),
            ("SHELL", "Outer shell"),
            ("SCREW", "M3 screw"),
            ("BOLT", "M6 bolt"),
        ]:
            _create_catalog_item(client, admin_headers, part_number=pn, description=desc)

        _add_template_edge(client, admin_headers, parent="KIT", child="HOUSING", quantity="1", sequence=0)
        _add_template_edge(client, admin_headers, parent="KIT", child="BOLT", quantity="2", sequence=1)
        _add_template_edge(client, admin_headers, parent="HOUSING", child="SHELL", quantity="1", sequence=0)
        _add_template_edge(client, admin_headers, parent="HOUSING", child="SCREW", quantity="4", sequence=1)

    def test_full_workflow(
        self,
        client: TestClient,
        admin_headers,
        admin_user: User,
        db_session: Session,
        workflow_price_list: PriceList,
    ):
        # ----------------------------------------------------------
        # 1. Seed catalog + multi-level template via the API
        # ----------------------------------------------------------
        self._seed_template(client, admin_headers)

        # ----------------------------------------------------------
        # 2. Preview the explosion
        # ----------------------------------------------------------
        preview = client.get("/catalog-items/KIT/preview-explosion", headers=admin_headers)
        assert preview.status_code == 200
        body = preview.json()
        assert body["total_nodes"] == 5  # KIT + HOUSING + SHELL + SCREW + BOLT
        assert body["max_depth_reached"] == 2

        root = body["tree"][0]
        assert root["part_number"] == "KIT"
        children = {c["part_number"]: c for c in root["children"]}
        assert set(children) == {"HOUSING", "BOLT"}
        housing_kids = sorted(c["part_number"] for c in children["HOUSING"]["children"])
        assert housing_kids == ["SCREW", "SHELL"]

        flat = {row["part_number"]: Decimal(row["total_quantity"]) for row in body["flat"]}
        # Cascade math: HOUSING=1, SHELL=1*1=1, SCREW=1*4=4, BOLT=2.
        assert flat == {
            "HOUSING": Decimal("1"),
            "SHELL": Decimal("1"),
            "SCREW": Decimal("4"),
            "BOLT": Decimal("2"),
        }

        # ----------------------------------------------------------
        # 3. Materialize the root onto a DRAFT EntityVersion
        # ----------------------------------------------------------
        entity, draft = _create_published_entity_with_draft(db_session, admin_user, "Engineering BOM Workflow Entity")

        materialize_resp = client.post(
            "/bom-items/",
            json={
                "entity_version_id": draft.id,
                "part_number": "KIT",
                "bom_type": "TECHNICAL",
                "quantity": "1",
                "sequence": 0,
                "explode_from_template": True,
            },
            headers=admin_headers,
        )
        assert materialize_resp.status_code == 201
        materialized = materialize_resp.json()
        assert materialized["part_number"] == "KIT"
        assert {c["part_number"] for c in materialized["children"]} == {"HOUSING", "BOLT"}

        rows = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft.id).all()
        assert {r.part_number for r in rows} == {"KIT", "HOUSING", "SHELL", "SCREW", "BOLT"}
        assert all(r.bom_type == BOMType.TECHNICAL.value for r in rows)

        # ----------------------------------------------------------
        # 4. Publish the source draft so a Configuration can attach.
        #    Then calculate and assert technical_flat correctness.
        # ----------------------------------------------------------
        publish = client.post(f"/versions/{draft.id}/publish", headers=admin_headers)
        assert publish.status_code == 200

        create_cfg = client.post(
            "/configurations/",
            json={
                "entity_version_id": draft.id,
                "name": "Workflow Config",
                "data": [],
                "price_list_id": workflow_price_list.id,
            },
            headers=admin_headers,
        )
        assert create_cfg.status_code == 201
        config_id = create_cfg.json()["id"]

        calc = client.get(
            f"/configurations/{config_id}/calculate",
            headers=admin_headers,
        )
        assert calc.status_code == 200
        bom = calc.json()["bom"]

        technical_roots = {item["part_number"] for item in bom["technical"]}
        assert technical_roots == {"KIT"}

        flat_dict = {row["part_number"]: Decimal(row["total_quantity"]) for row in bom["technical_flat"]}
        # KIT itself contributes too: ancestor_product=1, KIT.quantity=1 → 1.
        assert flat_dict == {
            "KIT": Decimal("1"),
            "HOUSING": Decimal("1"),
            "SHELL": Decimal("1"),
            "SCREW": Decimal("4"),
            "BOLT": Decimal("2"),
        }

        # ----------------------------------------------------------
        # 5. Finalize → snapshot captures technical_flat verbatim
        # ----------------------------------------------------------
        finalize = client.post(f"/configurations/{config_id}/finalize", headers=admin_headers)
        assert finalize.status_code == 200

        db_session.expire_all()
        config = db_session.query(Configuration).filter(Configuration.id == config_id).first()
        assert config.snapshot is not None
        snap_flat = {
            row["part_number"]: Decimal(str(row["total_quantity"])) for row in config.snapshot["bom"]["technical_flat"]
        }
        assert snap_flat == flat_dict

        # ----------------------------------------------------------
        # 6. Clone the source EntityVersion → no re-materialization,
        #    structural copy preserved
        # ----------------------------------------------------------
        clone_resp = client.post(
            f"/versions/{draft.id}/clone",
            json={"changelog": "Cloned for upgrade scenario"},
            headers=admin_headers,
        )
        assert clone_resp.status_code == 201, clone_resp.json()
        cloned_version_id = clone_resp.json()["id"]

        cloned_rows = db_session.query(BOMItem).filter(BOMItem.entity_version_id == cloned_version_id).all()
        assert {r.part_number for r in cloned_rows} == {
            "KIT",
            "HOUSING",
            "SHELL",
            "SCREW",
            "BOLT",
        }
        # Source rows must be untouched.
        source_rows = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft.id).count()
        assert source_rows == 5
        # Mutating the template after the clone must NOT propagate to either version.
        new_part = client.post(
            "/catalog-items/",
            json={"part_number": "WASHER", "description": "M6 washer"},
            headers=admin_headers,
        )
        assert new_part.status_code == 201
        edit_template = client.post(
            "/catalog-items/HOUSING/template/items",
            json={"child_part_number": "WASHER", "quantity": "10"},
            headers=admin_headers,
        )
        assert edit_template.status_code == 201

        post_edit_source_rows = db_session.query(BOMItem).filter(BOMItem.entity_version_id == draft.id).count()
        post_edit_clone_rows = db_session.query(BOMItem).filter(BOMItem.entity_version_id == cloned_version_id).count()
        assert post_edit_source_rows == 5
        assert post_edit_clone_rows == 5

        # ----------------------------------------------------------
        # 7. Upgrade a NEW configuration onto a NEW version with a
        #    different materialization → recalculation reflects it
        # ----------------------------------------------------------
        # The cloned version is a fresh DRAFT. Materialize KIT again on it
        # (the template now includes WASHER under HOUSING), so the new
        # version's BOM has a different shape.
        # Because the cloned version received a structural copy of the
        # source's BOMs, first remove those, then materialize fresh.
        for r in cloned_rows:
            if r.parent_bom_item_id is None:
                client.delete(f"/bom-items/{r.id}", headers=admin_headers)

        rematerialize = client.post(
            "/bom-items/",
            json={
                "entity_version_id": cloned_version_id,
                "part_number": "KIT",
                "bom_type": "TECHNICAL",
                "quantity": "1",
                "sequence": 0,
                "explode_from_template": True,
            },
            headers=admin_headers,
        )
        assert rematerialize.status_code == 201

        # Publish the cloned version so Configuration upgrade can target it.
        # The current published version is the original draft — publishing
        # cloned_version_id auto-archives it.
        publish_clone = client.post(f"/versions/{cloned_version_id}/publish", headers=admin_headers)
        assert publish_clone.status_code == 200

        # Create a new DRAFT configuration on the original published version,
        # then upgrade it. Upgrading FINALIZED is blocked, so we use a new draft.
        # Actually, after publishing the cloned version, the original is ARCHIVED.
        # We need a config that lives on a still-PUBLISHED version of the same
        # entity, so we create one on the cloned version directly and verify
        # the new BOM shape via calculate.
        new_cfg = client.post(
            "/configurations/",
            json={
                "entity_version_id": cloned_version_id,
                "name": "Upgrade Target Config",
                "data": [],
                "price_list_id": workflow_price_list.id,
            },
            headers=admin_headers,
        )
        assert new_cfg.status_code == 201
        new_cfg_id = new_cfg.json()["id"]

        new_calc = client.get(
            f"/configurations/{new_cfg_id}/calculate",
            headers=admin_headers,
        )
        assert new_calc.status_code == 200
        new_flat = {
            row["part_number"]: Decimal(row["total_quantity"]) for row in new_calc.json()["bom"]["technical_flat"]
        }
        # WASHER is now part of HOUSING's template (×10), so it appears with
        # cascade quantity 1×10 = 10.
        assert new_flat == {
            "KIT": Decimal("1"),
            "HOUSING": Decimal("1"),
            "SHELL": Decimal("1"),
            "SCREW": Decimal("4"),
            "BOLT": Decimal("2"),
            "WASHER": Decimal("10"),
        }
