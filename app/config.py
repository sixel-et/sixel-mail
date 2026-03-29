from pathlib import Path
from pydantic_settings import BaseSettings

TOKEN_DIR = Path.home() / ".config" / "sixel"


def _read_token(filename: str) -> str:
    """Read a token from the bind-mounted config dir, or return empty."""
    path = TOKEN_DIR / filename
    try:
        return path.read_text().strip()
    except (FileNotFoundError, PermissionError):
        return ""


class Settings(BaseSettings):
    database_url: str
    resend_api_key: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    signing_secret: str = "dev-signing-secret-change-in-prod"
    api_base_url: str = "http://localhost:8000"
    mail_domain: str = "sixel.email"
    cf_worker_secret: str = ""  # Shared secret for authenticating Cloudflare Email Worker
    cf_account_id: str = "16ba5057d0d3002e9b9531b40f79853e"  # Cloudflare account ID
    cf_kv_namespace_id: str = "e53c1e7905054c0a80bc2a7251410587"  # KV namespace ID
    cf_api_token: str = ""  # Cloudflare API token (for KV writes)

    model_config = {"env_file": ".env"}


settings = Settings()

# Fall back to bind-mounted token file if env var is empty
if not settings.cf_api_token:
    settings.cf_api_token = _read_token("cloudflare_token")
