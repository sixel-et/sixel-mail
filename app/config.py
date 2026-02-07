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

    model_config = {"env_file": ".env"}


settings = Settings()
