"""Application entry point.

Run locally with:
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI

from app.presentation.routes import router as generation_router

app = FastAPI(
    title="PhishingAgent API",
    version="0.1.0",
    description=(
        "Configurable, reproducible generator of synthetic phishing-simulation "
        "campaigns over email and SMS, for authorized security-awareness research."
    ),
)

app.include_router(generation_router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
