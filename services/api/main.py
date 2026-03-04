"""
API Service
===========
FastAPI application exposing REST endpoints for the monitoring system.
Registers route modules from the ``routes`` package.
"""

import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.auth_routes import router as auth_router
from routes.services_routes import router as services_router
from routes.health_routes import router as health_router
from routes.uptime_routes import router as uptime_router
from routes.alerts_routes import router as alerts_router
from routes.dashboard_routes import router as dashboard_router, broadcast_loop
from routes.incidents_routes import router as incidents_router
from routes.alert_rules_routes import router as alert_rules_router
from routes.metrics_routes import router as metrics_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("api")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Microservices Monitor API",
    description="REST API for monitoring microservice health, uptime, and alerts.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(services_router)
app.include_router(health_router)
app.include_router(uptime_router)
app.include_router(alerts_router)
app.include_router(dashboard_router)
app.include_router(incidents_router)
app.include_router(alert_rules_router)
app.include_router(metrics_router)


# ---------------------------------------------------------------------------
# Startup — launch WebSocket broadcast loop
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_loop())
    logger.info("WebSocket broadcast loop started")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
