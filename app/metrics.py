import time

from fastapi import FastAPI, Request
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Variant 13 bucket set Г3 (ms): 1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024
BUCKETS_SECONDS = (0.001, 0.002, 0.004, 0.008, 0.016, 0.032, 0.064, 0.128, 0.256, 0.512, 1.024)

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "code"]
)
REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=BUCKETS_SECONDS,
)
REQUESTS_IN_PROGRESS = Gauge("http_requests_in_progress", "HTTP requests currently being processed")


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        REQUESTS_IN_PROGRESS.inc()
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            REQUESTS_IN_PROGRESS.dec()
        duration = time.perf_counter() - start

        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path
        REQUEST_DURATION.labels(method=request.method, path=path).observe(duration)
        REQUEST_COUNT.labels(method=request.method, path=path, code=str(response.status_code)).inc()
        return response


def setup_metrics(app: FastAPI) -> None:
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
