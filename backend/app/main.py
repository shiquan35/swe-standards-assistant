from app.core.observability import setup_langtrace

setup_langtrace()

from fastapi import FastAPI, status
from fastapi.responses import RedirectResponse
from fastapi_pagination import add_pagination
from guard.middleware import SecurityMiddleware

from app.core.logger import app_logger
from app.core.security import security_config
from app.middlewares.process_time import ProcessTimeMiddleware  # noqa: E402
from app.routers.sample import router as sample_router  # noqa: E402
from app.routers.sample import observability_router  # noqa: E402
from app.routers.user import router as user_router  # noqa: E402

###################### FastAPI Setup START #############################

app = FastAPI(title="Developer Standards Assistant", version="0.1.0")
app.add_middleware(ProcessTimeMiddleware)
app.add_middleware(SecurityMiddleware, config=security_config)
app.include_router(sample_router, prefix="/api")
app.include_router(observability_router, prefix="/observability")
app.include_router(user_router)

add_pagination(app)
###################### FastAPI Setup END #############################

app_logger.debug("Starting application bootstrap phase")
app_logger.info("App startup complete. version={}", app.version)
app_logger.success("Sample router registered at /api")
app_logger.success("Observability router registered at /observability")
app_logger.warning("Demo warning (sample log)")


# redirect
@app.get("/", include_in_schema=False)
def redirect():
    return {"service": "Developer Standards Assistant"}


@app.get("/healthcheck", status_code=status.HTTP_200_OK)
def healthcheck():
    """Lightweight liveness probe.

    Returns HTTP 200 and a simple JSON payload when the application instance
    is running and able to serve requests. Intended for load balancers /
    uptime monitors (no downstream dependency checks).

    Response example:
        {"healthcheck": "OK!"}
    """
    return {"healthcheck": "OK!"}
