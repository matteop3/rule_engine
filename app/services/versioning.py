from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.domain import Entity, EntityVersion, Field, Value, Rule, VersionStatus
import copy

class VersioningService:

    def create_draft_version(self, db: Session, entity_id: int, user_id: str, changelog: Optional[str] = None) -> EntityVersion:
        """
        Creates a new DRAFT version.
        Enforces:
        - Entity existence check
        - Single Draft Policy (only one draft per entity)
        - Auto-increment version number
        """
        # Check if Entity exists
        entity = db.query(Entity).filter(Entity.id == entity_id).first()
        if not entity:
            raise ValueError(f"Entity {entity_id} not found.")

        # Check if DRAFT exists
        existing_draft = db.query(EntityVersion).filter(
            EntityVersion.entity_id == entity_id,
            EntityVersion.status == VersionStatus.DRAFT
        ).first()
        
        if existing_draft:
            raise ValueError(f"A DRAFT version ({existing_draft.version_number}) already exists. Publish or delete it first.")

        # Calculate next Version number
        last_ver = db.query(EntityVersion).filter(
            EntityVersion.entity_id == entity_id
        ).order_by(EntityVersion.version_number.desc()).first()
        
        next_num = last_ver.version_number + 1 if last_ver else 1

        # Create the object
        new_version = EntityVersion(
            entity_id=entity_id,
            version_number=next_num,
            status=VersionStatus.DRAFT,
            changelog=changelog,
            created_by_id=user_id,
            updated_by_id=user_id
        )
        
        db.add(new_version)
        return new_version

    def publish_version(self, db: Session, version_id: int, user_id: str) -> EntityVersion:
        """
        Promotes a DRAFT to PUBLISHED.
        Enforces:
        - Existence check
        - Status check (only DRAFT can be published)
        - Single Published Policy (archives the previous one)
        """
        version = db.query(EntityVersion).filter(EntityVersion.id == version_id).first()
        if not version:
            raise ValueError(f"Version {version_id} not found.")
        
        if version.status != VersionStatus.DRAFT:
            raise ValueError("Only DRAFT Versions can be published.")

        # Archive currently published Version (if any)
        current_published = db.query(EntityVersion).filter(
            EntityVersion.entity_id == version.entity_id,
            EntityVersion.status == VersionStatus.PUBLISHED
        ).first()
        
        if current_published:
            current_published.status = VersionStatus.ARCHIVED
        
        # Publish the new Version
        version.status = VersionStatus.PUBLISHED
        version.published_at = datetime.now(timezone.utc)
        version.updated_by_id = user_id

        return version

    def clone_version(self, db: Session, source_version_id: int, user_id: str, new_changelog: Optional[str] = None) -> EntityVersion:
        """
        Performs a deep copy of a source version into a new DRAFT version.
        Handles ID remapping for Fields, Values, and Rules (including JSON criteria).
        """
        
        # Fetch source version
        source_version = db.query(EntityVersion).filter(EntityVersion.id == source_version_id).first()
        if not source_version:
            raise ValueError(f"Source version {source_version_id} not found.")
        
        # Check if DRAFT exists
        existing_draft = db.query(EntityVersion).filter(
            EntityVersion.entity_id == source_version.entity_id,
            EntityVersion.status == VersionStatus.DRAFT
        ).first()
        
        if existing_draft:
             raise ValueError(f"A DRAFT version ({existing_draft.version_number}) already exists.")

        # Calculate new version number
        last_ver = db.query(EntityVersion).filter(
            EntityVersion.entity_id == source_version.entity_id
        ).order_by(EntityVersion.version_number.desc()).first()
        
        next_num = last_ver.version_number + 1 if last_ver else 1

        # Create the new Version container
        new_version = EntityVersion(
            entity_id=source_version.entity_id,
            version_number=next_num,
            status=VersionStatus.DRAFT,
            changelog=new_changelog or f"Cloned from v{source_version.version_number}.",
            created_by_id=user_id,
            updated_by_id=user_id
        )
        db.add(new_version)
        db.flush() # Flush to generate new_version.id

        # Mapping dictionaries (old ID -> new ID)
        field_map: Dict[int, int] = {}
        value_map: Dict[int, int] = {}

        # Clone Fields and Values
        # Fetch fields from source
        source_fields = db.query(Field).filter(Field.entity_version_id == source_version.id).all()

        for old_field in source_fields:
            # Clone Field
            new_field = Field(
                entity_version_id=new_version.id,
                name=old_field.name,
                data_type=old_field.data_type,
                is_required=old_field.is_required,
                is_readonly=old_field.is_readonly,
                is_hidden=old_field.is_hidden,
                is_free_value=old_field.is_free_value,
                default_value=old_field.default_value,
                step=old_field.step,
                sequence=old_field.sequence
            )
            db.add(new_field)
            db.flush() # Get new_field.id
            
            # Store mapping
            field_map[old_field.id] = new_field.id

            # Clone Values for this Field
            for old_val in old_field.values:
                new_val = Value(
                    field_id=new_field.id, # Link to NEW field
                    value=old_val.value,
                    label=old_val.label,
                    is_default=old_val.is_default
                )
                db.add(new_val)
                db.flush() # Get new_val.id
                
                # Store mapping
                value_map[old_val.id] = new_val.id

        # Clone Rules
        source_rules = db.query(Rule).filter(Rule.entity_version_id == source_version.id).all()

        for old_rule in source_rules:
            # Resolve new target IDs
            new_target_field_id = field_map.get(old_rule.target_field_id)
            
            # If target field is missing in map (should not happen), skip or error
            if not new_target_field_id:
                continue

            new_target_value_id = None
            if old_rule.target_value_id:
                new_target_value_id = value_map.get(old_rule.target_value_id)

            # Rewrite JSON conditions
            # Iterate over criteria and update 'field_id'
            new_conditions = self._rewrite_conditions(old_rule.conditions, field_map)

            new_rule = Rule(
                entity_version_id=new_version.id,
                target_field_id=new_target_field_id,
                target_value_id=new_target_value_id,
                rule_type=old_rule.rule_type,
                description=old_rule.description,
                conditions=new_conditions
            )
            db.add(new_rule)

        return new_version

    def _rewrite_conditions(self, conditions: Dict[str, Any], field_map: Dict[int, int]) -> Dict[str, Any]:
        """ Helper to traverse the JSON structure and update field IDs. """
        new_cond = copy.deepcopy(conditions) # Avoid modifying the original object in memory
        
        criteria_list = new_cond.get("criteria", [])
        for criterion in criteria_list:
            old_fid = criterion.get("field_id")
            if old_fid in field_map:
                criterion["field_id"] = field_map[old_fid]
        
        return new_cond