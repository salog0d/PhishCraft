"""Application entry point.

Run locally with:
    uvicorn app.main:app --reload
"""

import time

from fastapi import FastAPI

from app.presentation.routes import router as generation_router

try:
    from monitoring import metrics
except ImportError:  # pragma: no cover — metrics are optional
    metrics = None

app = FastAPI(
    title="PhishingAgent API",
    version="0.1.0",
    description=(
        "Configurable, reproducible generator of synthetic phishing-simulation "
        "campaigns over email and SMS, for authorized security-awareness research."
    ),
)

app.include_router(generation_router)

# Prometheus scrape endpoint (standard /metrics convention for scrapers).
@app.get("/metrics", include_in_schema=False)
def metrics_endpoint():
    """Serve the default registry (process + phishcraft_http_* metrics)."""
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
        from fastapi.responses import Response

        return Response(
            content=generate_latest(), media_type=CONTENT_TYPE_LATEST
        )
    except ImportError:  # pragma: no cover
        return {"status": "prometheus_client not installed"}


@app.middleware("http")
async def metrics_middleware(request, call_next):
    """Count and time every API request (route template, not raw path)."""
    if request.url.path == "/metrics":
        return await call_next(request)
    t0 = time.monotonic()
    response = await call_next(request)
    # Route matching happens inside call_next — read the template afterwards.
    route = getattr(request.scope.get("route"), "path", None) or "other"
    if metrics is not None:
        metrics.HTTP_REQUESTS.labels(
            method=request.method, route=route, status=response.status_code
        ).inc()
        metrics.HTTP_DURATION.labels(
            method=request.method, route=route, status=response.status_code
        ).observe(time.monotonic() - t0)
    return response


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
