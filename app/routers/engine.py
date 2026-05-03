import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import fetch_version_by_id, get_current_user, get_rule_engine_service
from app.models.domain import User, UserRole, VersionStatus
from app.schemas.engine import CalculationRequest, CalculationResponse
from app.services.rule_engine import RuleEngineService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/engine", tags=["Engine"])


def validate_user_can_calculate_version(
    user: User, request: CalculationRequest, version_status: VersionStatus | None
) -> None:
    """Allow USERs only on PUBLISHED versions; ADMIN/AUTHOR can calculate on any version (raises 403)."""
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
            detail="Regular users can only calculate state on PUBLISHED versions.",
        )


def handle_calculation_error(e: ValueError) -> HTTPException:
    """Map an engine `ValueError` to 404 (`not found` / `no PUBLISHED version`) or 400 otherwise."""
    msg: str = str(e)
    msg_lower = msg.lower()

    if "not found" in msg_lower or "no published version" in msg_lower:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)

    # All other business logic errors
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


@router.post("/calculate", response_model=CalculationResponse)
def calculate_state(
    request: CalculationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # Auth
    engine_service: RuleEngineService = Depends(get_rule_engine_service),
):
    """Stateless rule-engine calculation against the requested (or PUBLISHED) version.

    USER role can only target PUBLISHED versions; ADMIN/AUTHOR can preview any version.
    """
    logger.info(
        f"Calculation request by user {current_user.id} (role: {current_user.role_display}): "
        f"entity_id={request.entity_id}, version_id={request.entity_version_id or 'PUBLISHED'}"
    )

    # Access control
    if request.entity_version_id is not None:
        # Fetch version (raises 404 if not found)
        version = fetch_version_by_id(db, request.entity_version_id)

        # Validate permissions
        validate_user_can_calculate_version(current_user, request, version.status)
        logger.debug(
            f"Access granted: user {current_user.id} can calculate on version {version.id} (status: {version.status})"
        )

    # Calculation
    try:
        response: CalculationResponse = engine_service.calculate_state(db, request)

        logger.info(
            f"Calculation successful for user {current_user.id}: "
            f"entity_id={request.entity_id}, is_complete={response.is_complete}, "
            f"fields_count={len(response.fields)}"
        )

        return response

    except ValueError as e:
        raise handle_calculation_error(e) from None

    except Exception:
        logger.exception(
            f"Unexpected error during calculation for user {current_user.id}",
            extra={"entity_id": request.entity_id, "user_id": current_user.id},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during calculation. Please try again later.",
        ) from None
