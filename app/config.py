from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-2"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    signing_secret: str = "dev-signing-secret-change-in-prod"
    api_base_url: str = "http://localhost:8000"
    mail_domain: str = "sixel.email"
    cf_worker_secret: str = ""  # Shared secret for authenticating Cloudflare Email Worker
    cf_account_id: str = ""  # Cloudflare account ID (for KV API)
    cf_kv_namespace_id: str = ""  # Cloudflare KV namespace ID (agent→contact mappings)
    cf_api_token: str = ""  # Cloudflare API token (for KV writes)

    model_config = {"env_file": ".env"}


settings = Settings()
