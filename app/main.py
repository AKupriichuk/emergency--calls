import socket

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.errors import ApiError
from app.metrics import setup_metrics
from app.routers.emergency_calls import router

app = FastAPI(title="Emergency Calls Service")
app.include_router(router)
setup_metrics(app)


class InstanceHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Instance-Id"] = socket.gethostname()
        return response


app.add_middleware(InstanceHeaderMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first_error = exc.errors()[0]
    loc = first_error["loc"]
    field = loc[-1] if len(loc) >= 2 and isinstance(loc[-1], str) else None
    return JSONResponse(status_code=400, content={"error": first_error["msg"], "field": field})


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message, "field": exc.field})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": "internal server error"})
