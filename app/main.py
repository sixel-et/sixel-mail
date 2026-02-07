import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import close_pool, get_pool
from app.routes.account import router as account_router
from app.routes.alerts import router as alerts_router
from app.routes.api import router as api_router
from app.routes.landing import router as landing_router
from app.routes.signup import router as signup_router
from app.routes.webhooks import router as webhooks_router
from app.services.heartbeat import heartbeat_loop

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await get_pool()
    logging.info("Database pool created")
    task = asyncio.create_task(heartbeat_loop())
    yield
    # Shutdown
    task.cancel()
    await close_pool()
    logging.info("Database pool closed")


app = FastAPI(title="Sixel-Mail", version="0.1.0", lifespan=lifespan)
app.include_router(landing_router)
app.include_router(api_router)
app.include_router(webhooks_router)
app.include_router(signup_router)
app.include_router(alerts_router)
app.include_router(account_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
