"""
Global Dependencies for the API.

Re-exports all public names for backward compatibility.
Existing ``from app.dependencies import X`` statements continue to work unchanged.
"""

from app.dependencies.auth import (
    get_current_user,
    oauth2_scheme,
    require_admin_or_author,
    require_role,
)
from app.dependencies.fetchers import (
    fetch_bom_item_by_id,
    fetch_bom_item_rule_by_id,
    fetch_entity_by_id,
    fetch_field_by_id,
    fetch_rule_by_id,
    fetch_user_by_id,
    fetch_value_by_id,
    fetch_version_by_id,
    get_bom_item_or_404,
    get_bom_item_rule_or_404,
    get_entity_or_404,
    get_field_or_404,
    get_rule_or_404,
    get_user_or_404,
    get_value_or_404,
    get_version_or_404,
)
from app.dependencies.services import (
    db_transaction,
    get_auth_service,
    get_rule_engine_service,
    get_user_service,
    get_versioning_service,
)
from app.dependencies.validators import (
    _is_finalized,
    get_editable_bom_item,
    get_editable_bom_item_rule,
    get_editable_field,
    get_editable_rule,
    get_editable_value,
    get_editable_version,
    require_complete_status,
    require_draft_status,
    validate_catalog_not_referenced,
    validate_catalog_reference,
    validate_field_belongs_to_version,
    validate_value_belongs_to_field,
    validate_value_not_used_in_rules,
    validate_version_is_draft,
)

__all__ = [
    # auth
    "oauth2_scheme",
    "get_current_user",
    "require_role",
    "require_admin_or_author",
    # services
    "get_auth_service",
    "get_user_service",
    "get_rule_engine_service",
    "get_versioning_service",
    "db_transaction",
    # fetchers
    "fetch_user_by_id",
    "fetch_entity_by_id",
    "fetch_field_by_id",
    "fetch_rule_by_id",
    "fetch_value_by_id",
    "fetch_version_by_id",
    "fetch_bom_item_by_id",
    "fetch_bom_item_rule_by_id",
    "get_user_or_404",
    "get_entity_or_404",
    "get_field_or_404",
    "get_rule_or_404",
    "get_value_or_404",
    "get_version_or_404",
    "get_bom_item_or_404",
    "get_bom_item_rule_or_404",
    # validators
    "_is_finalized",
    "require_draft_status",
    "require_complete_status",
    "validate_catalog_not_referenced",
    "validate_catalog_reference",
    "validate_field_belongs_to_version",
    "validate_value_belongs_to_field",
    "validate_value_not_used_in_rules",
    "validate_version_is_draft",
    "get_editable_version",
    "get_editable_field",
    "get_editable_rule",
    "get_editable_value",
    "get_editable_bom_item",
    "get_editable_bom_item_rule",
]
