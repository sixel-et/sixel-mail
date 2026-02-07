import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import close_pool, get_pool
from app.routes.api import router as api_router
from app.routes.webhooks import router as webhooks_router

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await get_pool()
    logging.info("Database pool created")
    yield
    # Shutdown
    await close_pool()
    logging.info("Database pool closed")


app = FastAPI(title="Sixel-Mail", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)
app.include_router(webhooks_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
