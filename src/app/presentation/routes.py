"""HTTP routes for the phishing-campaign generator API."""

from fastapi import APIRouter, HTTPException, status

from app.core.schemas import PhishingGenerationRequest, PhishingGenerationResponse

router = APIRouter(prefix="/generation", tags=["generation"])


@router.post(
    "/messages",
    response_model=PhishingGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a simulation message (email or SMS) for generation",
)
def submit_generation_request(
    request: PhishingGenerationRequest,
) -> PhishingGenerationResponse:
    """Validate a generation request and acknowledge acceptance.

    FastAPI validates the payload against ``PhishingGenerationRequest`` before
    this runs; a malformed body — including a wrong channel/model combination —
    is rejected with ``422`` automatically. The request names the target
    ``channel`` (email or sms) and the ``model`` adapter to generate with; the
    engine's actual composition step is not wired up yet, so this returns a
    success acknowledgement.
    """
    if not request.authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Campaign must be attested as authorized.",
        )

    return PhishingGenerationResponse(campaign_id=request.campaign_id)
