from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.engine import CalculationRequest, CalculationResponse
from app.services import RuleEngineService

router = APIRouter(
    prefix="/engine",
    tags=["Engine"]
)

@router.post("/calculate", response_model=CalculationResponse)
def calculate_state(request: CalculationRequest, db: Session = Depends(get_db)):
    """
    Endpoint to trigger the Rule Engine calculation.
    It takes the current state of the entity (user inputs) and returns
    the calculated state (available options, visibility, valid values) based on the rules.
    """
    # Instantiate the service (stateless)
    service = RuleEngineService()

    try:
        # Delegate the complex waterfall logic to the Service Layer
        response = service.calculate_state(db, request)
        return response
    except ValueError as e:
        # Handle cases where the entity ID provided does not exist
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        # Generic fallback for unexpected errors to avoid crashing the server silently
        # In production, you would log the stack trace here
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))