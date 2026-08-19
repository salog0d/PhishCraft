"""HTTP routes for the phishing-simulation generator API."""

from fastapi import APIRouter, HTTPException, status

from app.core.schemas import PhishingGenerationRequest, PhishingGenerationResponse

router = APIRouter(prefix="/generation", tags=["generation"])


@router.post(
    "/emails",
    response_model=PhishingGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a simulation email for generation",
)
def submit_generation_request(
    request: PhishingGenerationRequest,
) -> PhishingGenerationResponse:
    """Validate a generation request and acknowledge acceptance.

    FastAPI validates the payload against ``PhishingGenerationRequest`` before
    this runs; a malformed body is rejected with ``422`` automatically. The
    engine's actual composition step is not wired up yet — this returns a
    success response.
    """
    if not request.authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Campaign must be attested as authorized.",
        )

    return PhishingGenerationResponse(campaign_id=request.campaign_id)
