"""Application entry point.

Run locally with:
    uvicorn app.main:app --reload
"""

from fastapi import FastAPI

from app.presentation.routes import router as analysis_router

app = FastAPI(
    title="PhishingAgent API",
    version="0.1.0",
    description="Service that accepts emails and analyses them for phishing.",
)

app.include_router(analysis_router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
