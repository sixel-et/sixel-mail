import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from app.db import close_pool, get_pool
from app.routes.account import router as account_router
from app.routes.alerts import router as alerts_router
from app.routes.allstop import router as allstop_router
from app.routes.api import router as api_router
from app.routes.landing import router as landing_router
from app.routes.signup import router as signup_router
from app.routes.admin import router as admin_router
from app.routes.bestpractices import router as bestpractices_router
from app.routes.blog import router as blog_router
from app.routes.webhooks import router as webhooks_router
from app.services.heartbeat import heartbeat_loop

logging.basicConfig(level=logging.INFO)


async def run_migrations():
    """Run pending database migrations on startup.

    Each migration is idempotent (uses IF NOT EXISTS / IF NOT EXISTS).
    Tracks applied migrations in a migrations table.
    """
    pool = await get_pool()

    # Create migrations tracking table if it doesn't exist
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ DEFAULT now()
        )
    """)

    import pathlib
    migrations_dir = pathlib.Path(__file__).parent.parent / "migrations"
    if not migrations_dir.exists():
        return

    applied = {row["filename"] for row in await pool.fetch("SELECT filename FROM _migrations")}

    for sql_file in sorted(migrations_dir.glob("*.sql")):
        if sql_file.name in applied:
            continue
        logging.info("Running migration: %s", sql_file.name)
        sql = sql_file.read_text()
        await pool.execute(sql)
        await pool.execute("INSERT INTO _migrations (filename) VALUES ($1)", sql_file.name)
        logging.info("Migration applied: %s", sql_file.name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await get_pool()
    logging.info("Database pool created")
    await run_migrations()
    task = asyncio.create_task(heartbeat_loop())
    yield
    # Shutdown
    task.cancel()
    await close_pool()
    logging.info("Database pool closed")


app = FastAPI(title="Sixel-Mail", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(landing_router)
app.include_router(api_router)
app.include_router(webhooks_router)
app.include_router(signup_router)
app.include_router(alerts_router)
app.include_router(account_router)
app.include_router(admin_router)
app.include_router(allstop_router)
app.include_router(bestpractices_router)
app.include_router(blog_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return "User-agent: *\nAllow: /\nSitemap: https://sixel.email/sitemap.xml\n"


@app.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap_xml():
    from app.routes.blog import POSTS
    blog_urls = "\n".join(
        f'  <url><loc>https://sixel.email/blog/{p["slug"]}</loc><priority>0.6</priority></url>'
        for p in POSTS
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://sixel.email/</loc><priority>1.0</priority></url>
  <url><loc>https://sixel.email/best-practices</loc><priority>0.8</priority></url>
  <url><loc>https://sixel.email/blog</loc><priority>0.8</priority></url>
{blog_urls}
  <url><loc>https://sixel.email/donate</loc><priority>0.3</priority></url>
</urlset>"""
