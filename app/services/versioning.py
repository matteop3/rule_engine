import copy
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.models.domain import BOMItem, BOMItemRule, Entity, EntityVersion, Field, Rule, Value, VersionStatus

logger = logging.getLogger(__name__)


class VersioningService:
    """
    Service for managing Entity versioning lifecycle.

    Transaction Management:
    This service does NOT handle database commits.
    The caller is responsible for:
    - db.commit() on success
    - db.rollback() on exception
    """

    # ============================================================
    # PUBLIC API
    # ============================================================

    def create_draft_version(
        self,
        db: Session,
        entity_id: int,
        user_id: str,
        changelog: str | None = None,
        sku_base: str | None = None,
        sku_delimiter: str | None = None,
    ) -> EntityVersion:
        """
        Creates a new DRAFT version.
        Enforces:
        - Entity existence check
        - Single Draft Policy (only one draft per entity)
        - Auto-increment version number
        """
        logger.debug("Creating draft version", extra={"entity_id": entity_id, "user_id": user_id})

        self._check_entity_exists(db, entity_id)
        self._check_draft_constraint(db, entity_id)

        next_num = self._calculate_next_version_number(db, entity_id)
        new_version = self._create_version_entity(entity_id, next_num, user_id, changelog, sku_base, sku_delimiter)

        db.add(new_version)
        db.flush()

        logger.info(
            "Draft version created",
            extra={
                "version_id": new_version.id,
                "entity_id": entity_id,
                "version_number": next_num,
                "user_id": user_id,
            },
        )

        return new_version

    def publish_version(self, db: Session, version_id: int, user_id: str) -> EntityVersion:
        """
        Promotes a DRAFT to PUBLISHED.
        Enforces:
        - Existence check
        - Status check (only DRAFT can be published)
        - Single Published Policy (archives the previous one)
        """
        logger.debug("Publishing version", extra={"version_id": version_id, "user_id": user_id})

        version = self._get_version_by_id(db, version_id)

        if version.status != VersionStatus.DRAFT:
            raise ValueError("Only DRAFT Versions can be published.")

        # Archive currently published Version (if any)
        current_published = (
            db.query(EntityVersion)
            .filter(EntityVersion.entity_id == version.entity_id, EntityVersion.status == VersionStatus.PUBLISHED)
            .first()
        )

        if current_published:
            current_published.status = VersionStatus.ARCHIVED

            # Invalidate cached data for the archived version
            from app.dependencies.services import get_rule_engine_service

            get_rule_engine_service()._cache.invalidate(str(current_published.id))

            logger.info(
                "Previous version archived",
                extra={"archived_version_id": current_published.id, "version_number": current_published.version_number},
            )

        # Publish the new Version
        version.status = VersionStatus.PUBLISHED
        version.published_at = datetime.now(UTC)
        version.updated_by_id = user_id

        logger.info(
            "Version published",
            extra={
                "version_id": version_id,
                "entity_id": version.entity_id,
                "version_number": version.version_number,
                "user_id": user_id,
            },
        )

        return version

    def clone_version(
        self, db: Session, source_version_id: int, user_id: str, new_changelog: str | None = None
    ) -> EntityVersion:
        """
        Performs a deep copy of a source version into a new DRAFT version.

        Handles:
        - ID remapping for Fields, Values, and Rules
        - JSON criteria rewriting
        - Eager loading to avoid N+1 queries
        """
        logger.debug("Cloning version", extra={"source_version_id": source_version_id, "user_id": user_id})

        # Fetch source version with eager loading (avoid N+1)
        source_version = (
            db.query(EntityVersion)
            .options(
                joinedload(EntityVersion.fields).joinedload(Field.values),
                joinedload(EntityVersion.rules),
                joinedload(EntityVersion.bom_items).joinedload(BOMItem.rules),
            )
            .filter(EntityVersion.id == source_version_id)
            .first()
        )

        if not source_version:
            raise ValueError(f"Source version {source_version_id} not found.")

        self._check_draft_constraint(db, source_version.entity_id)

        next_num = self._calculate_next_version_number(db, source_version.entity_id)
        changelog = new_changelog or f"Cloned from v{source_version.version_number}."

        new_version = self._create_version_entity(
            source_version.entity_id,
            next_num,
            user_id,
            changelog,
            sku_base=source_version.sku_base,
            sku_delimiter=source_version.sku_delimiter,
        )
        db.add(new_version)
        db.flush()

        # Mapping dictionaries (old ID -> new ID)
        field_map: dict[int, int] = {}
        value_map: dict[int, int] = {}

        # Clone Fields and Values
        for old_field in source_version.fields:
            # Clone Field
            new_field = Field(
                entity_version_id=new_version.id,
                name=old_field.name,
                label=old_field.label,
                data_type=old_field.data_type,
                is_required=old_field.is_required,
                is_readonly=old_field.is_readonly,
                is_hidden=old_field.is_hidden,
                is_free_value=old_field.is_free_value,
                default_value=old_field.default_value,
                step=old_field.step,
                sequence=old_field.sequence,
            )
            db.add(new_field)
            db.flush()  # Get new_field.id

            # Store mapping
            field_map[old_field.id] = new_field.id

            # Clone Values for this Field
            for old_val in old_field.values:
                new_val = Value(
                    field_id=new_field.id,  # Link to new Field
                    value=old_val.value,
                    label=old_val.label,
                    is_default=old_val.is_default,
                )
                db.add(new_val)
                db.flush()  # Get new_val.id

                # Store mapping
                value_map[old_val.id] = new_val.id

        # Clone Rules
        for old_rule in source_version.rules:
            # Resolve new target IDs
            new_target_field_id = field_map.get(old_rule.target_field_id)

            # If target field is missing in map (should not happen), skip or error
            if not new_target_field_id:
                raise ValueError(f"Missing target Field for Rule {old_rule.id}.")

            new_target_value_id = None
            if old_rule.target_value_id:
                new_target_value_id = value_map.get(old_rule.target_value_id)
                if not new_target_value_id:
                    raise ValueError(f"Missing target Value for Rule {old_rule.id}.")

            # Rewrite JSON conditions
            # Iterate over criteria and update 'field_id'
            new_conditions = self._rewrite_conditions(old_rule.conditions, field_map)

            new_rule = Rule(
                entity_version_id=new_version.id,
                target_field_id=new_target_field_id,
                target_value_id=new_target_value_id,
                rule_type=old_rule.rule_type,
                description=old_rule.description,
                conditions=new_conditions,
                error_message=old_rule.error_message,
                set_value=old_rule.set_value,
            )
            db.add(new_rule)

        # Clone BOM Items (parents before children)
        bom_item_map: dict[int, int] = {}
        root_items = [bi for bi in source_version.bom_items if bi.parent_bom_item_id is None]
        child_items = [bi for bi in source_version.bom_items if bi.parent_bom_item_id is not None]

        for old_bom_item in root_items + child_items:
            new_parent_id = None
            if old_bom_item.parent_bom_item_id is not None:
                new_parent_id = bom_item_map.get(old_bom_item.parent_bom_item_id)
                if new_parent_id is None:
                    raise ValueError(f"Missing parent BOM item for BOMItem {old_bom_item.id}.")

            new_quantity_field_id = None
            if old_bom_item.quantity_from_field_id is not None:
                new_quantity_field_id = field_map.get(old_bom_item.quantity_from_field_id)
                if new_quantity_field_id is None:
                    raise ValueError(
                        f"Missing Field {old_bom_item.quantity_from_field_id} in field_map "
                        f"for BOMItem {old_bom_item.id} quantity_from_field_id."
                    )

            new_bom_item = BOMItem(
                entity_version_id=new_version.id,
                parent_bom_item_id=new_parent_id,
                bom_type=old_bom_item.bom_type,
                part_number=old_bom_item.part_number,
                quantity=old_bom_item.quantity,
                quantity_from_field_id=new_quantity_field_id,
                sequence=old_bom_item.sequence,
            )
            db.add(new_bom_item)
            db.flush()

            bom_item_map[old_bom_item.id] = new_bom_item.id

        # Clone BOM Item Rules
        for old_bom_item in source_version.bom_items:
            for old_bom_rule in old_bom_item.rules:
                new_bom_item_id = bom_item_map.get(old_bom_rule.bom_item_id)
                if new_bom_item_id is None:
                    raise ValueError(f"Missing BOM item for BOMItemRule {old_bom_rule.id}.")

                new_conditions = self._rewrite_conditions(old_bom_rule.conditions, field_map)

                new_bom_rule = BOMItemRule(
                    bom_item_id=new_bom_item_id,
                    entity_version_id=new_version.id,
                    conditions=new_conditions,
                    description=old_bom_rule.description,
                )
                db.add(new_bom_rule)

        logger.info(
            "Version cloned",
            extra={
                "new_version_id": new_version.id,
                "source_version_id": source_version_id,
                "entity_id": source_version.entity_id,
                "version_number": next_num,
                "fields_cloned": len(field_map),
                "values_cloned": len(value_map),
                "rules_cloned": len(source_version.rules),
                "bom_items_cloned": len(bom_item_map),
                "bom_item_rules_cloned": sum(len(bi.rules) for bi in source_version.bom_items),
                "user_id": user_id,
            },
        )

        return new_version

    # ============================================================
    # PRIVATE HELPERS
    # ============================================================

    def _create_version_entity(
        self,
        entity_id: int,
        version_number: int,
        user_id: str,
        changelog: str | None = None,
        sku_base: str | None = None,
        sku_delimiter: str | None = None,
    ) -> EntityVersion:
        """Creates a new EntityVersion object in DRAFT status."""
        return EntityVersion(
            entity_id=entity_id,
            version_number=version_number,
            status=VersionStatus.DRAFT,
            changelog=changelog,
            sku_base=sku_base,
            sku_delimiter=sku_delimiter,
            created_by_id=user_id,
            updated_by_id=user_id,
        )

    def _get_version_by_id(self, db: Session, version_id: int) -> EntityVersion:
        """Fetches a version by ID. Raises ValueError if not found."""
        version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()
        if not version:
            raise ValueError(f"Version {version_id} not found.")
        return version

    def _rewrite_conditions(self, conditions: dict[str, Any], field_map: dict[int, int]) -> dict[str, Any]:
        """
        Helper to traverse the JSON structure and update field IDs.

        Expected structure:
        {
            "criteria": [
                {"field_id": 123, "operator": "==", "value": "x"},
                ...
            ]
        }
        """
        new_cond = copy.deepcopy(conditions)  # Avoid modifying the original object in memory

        criteria_list = new_cond.get("criteria", [])
        for criterion in criteria_list:
            old_fid = criterion.get("field_id")
            if old_fid in field_map:
                criterion["field_id"] = field_map[old_fid]
            else:
                raise ValueError(f"Missing Field {old_fid} in field_map during conditions rewrite.")

        return new_cond

    def _check_entity_exists(self, db: Session, entity_id: int) -> Entity:
        """Raises ValueError if Entity does not exist."""
        entity = db.query(Entity).filter(Entity.id == entity_id).first()
        if not entity:
            raise ValueError(f"Entity {entity_id} not found.")
        return entity

    def _check_draft_constraint(self, db: Session, entity_id: int) -> None:
        """
        Enforces Single Draft Policy.
        Raises ValueError if a DRAFT already exists.
        """
        existing_draft = (
            db.query(EntityVersion)
            .filter(EntityVersion.entity_id == entity_id, EntityVersion.status == VersionStatus.DRAFT)
            .first()
        )

        if existing_draft:
            raise ValueError(
                f"A DRAFT version ({existing_draft.version_number}) already exists. Publish or delete it first."
            )

    def _calculate_next_version_number(self, db: Session, entity_id: int) -> int:
        """Returns the next available version number for an Entity."""
        last_version = (
            db.query(EntityVersion)
            .filter(EntityVersion.entity_id == entity_id)
            .order_by(EntityVersion.version_number.desc())
            .first()
        )

        return (last_version.version_number + 1) if last_version else 1
