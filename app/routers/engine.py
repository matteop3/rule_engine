from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import logging
from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.engine import CalculationRequest, CalculationResponse
from app.models.domain import User, UserRole, VersionStatus, EntityVersion
from app.services.rule_engine import RuleEngineService
from app.dependencies import get_rule_engine_service

router = APIRouter(
    prefix="/engine",
    tags=["Engine"]
)

logger = logging.getLogger(__name__)


# ============================================================
# HELPERS
# ============================================================

def validate_user_can_calculate_version(
    user: User, 
    request: CalculationRequest,
    version_status: Optional[VersionStatus]
) -> None:
    """
    Enforces access control for calculation requests.
    
    Rules:
    - USER: Can only calculate on PUBLISHED versions
    - AUTHOR/ADMIN: Can calculate on any version (including DRAFT for testing)
    
    Args:
        user: Current authenticated user
        request: Calculation request containing version info
        version_status: Status of the version being calculated (if known)
    
    Raises:
        HTTPException(403): If user lacks permission
    """
    # If no specific version requested, it defaults to PUBLISHED (always allowed)
    if request.entity_version_id is None:
        return
    
    # If version status is known and it's PUBLISHED, allow for everyone
    if version_status == VersionStatus.PUBLISHED:
        return
    
    # For non-PUBLISHED versions (DRAFT, ARCHIVED), only AUTHOR/ADMIN
    if user.role == UserRole.USER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Regular users can only calculate state on PUBLISHED versions."
        )


def handle_calculation_error(e: ValueError) -> HTTPException:
    """
    Maps service ValueError to appropriate HTTP exception.
    
    Business logic errors are categorized as:
    - "not found" → 404
    - "no PUBLISHED version" → 404 (entity exists but not ready)
    - Other validation errors → 400
    """
    msg: str = str(e)
    msg_lower = msg.lower()
    
    if "not found" in msg_lower or "no published version" in msg_lower:
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=msg
        )
    
    # All other business logic errors
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=msg
    )


# ============================================================
# ENDPOINTS
# ============================================================

@router.post("/calculate", response_model=CalculationResponse)
def calculate_state(
    request: CalculationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth
    engine_service: RuleEngineService = Depends(get_rule_engine_service)
):
    """
    Triggers the Rule Engine calculation.
    
    Workflow:
    1. Resolves target version (explicit or PUBLISHED by default)
    2. Evaluates all rules in waterfall sequence
    3. Returns calculated field states with available options
    
    Access Control:
    - USER: Can only calculate on PUBLISHED versions
    - AUTHOR/ADMIN: Can calculate on any version (including DRAFT for preview)
    
    Request Body:
        entity_id: The entity to calculate
        entity_version_id (optional): Specific version to use (defaults to PUBLISHED)
        current_state: List of field inputs (field_id + value)
    
    Returns:
        CalculationResponse: Full field states with:
        - available_options (filtered by rules)
        - is_required, is_readonly, is_hidden flags
        - validation errors
        - is_complete flag (all required fields filled and no validation errors)
    
    Raises:
        HTTPException(400): Invalid input data or business logic error
        HTTPException(403): User lacks permission for requested version
        HTTPException(404): Entity or version not found
        HTTPException(500): Unexpected server error
    """

    # Access control
    if request.entity_version_id is not None:
        version = db.query(EntityVersion).filter(
            EntityVersion.id == request.entity_version_id
        ).first()
        
        # Fail immediately if version doesn't exist
        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entity Version {request.entity_version_id} not found."
            )
        
        # Safely validate permissions
        validate_user_can_calculate_version(current_user, request, version.status)
    
    # Calculation
    try:
        response: CalculationResponse = engine_service.calculate_state(db, request)
        return response
    
    except ValueError as e:
        logger.warning(
            f"Calculation failed for user {current_user.id}: {str(e)}",
            extra={"entity_id": request.entity_id, "user_id": current_user.id}
        )
        raise handle_calculation_error(e)
    
    except Exception as e:
        logger.exception(
            f"Unexpected error during calculation for user {current_user.id}",
            extra={"entity_id": request.entity_id, "user_id": current_user.id}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during calculation. Please try again later."
        )