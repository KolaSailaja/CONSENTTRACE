from __future__ import annotations

import base64
import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    app_env: str = "development"
    app_mode: str = ""
    postgres_db: str = "consenttrace"
    postgres_user: str = "consenttrace"
    postgres_password: str = "consenttrace"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "consenttrace"
    backend_port: int = 8000
    frontend_url: str = "http://localhost:3000"
    data_dir: str = str(BASE_DIR / "data")
    database_url: str | None = None
    sandbox_enabled: bool = False
    api_key_pepper: str = "local-development-only-api-key-pepper"
    api_key_encryption_key: str = ""
    dev_bootstrap_api_key: str = ""
    dev_bootstrap_org_id: str = "org-acmepay-demo"
    sandbox_connector_api_key: str = ""
    sandbox_admin_api_key: str = ""
    production_admin_api_key: str = ""
    production_admin_org_id: str = ""
    trusted_proxy_headers: bool = False
    max_json_body_bytes: int = 1_048_576
    max_ingestion_event_bytes: int = 262_144
    max_evidence_payload_bytes: int = 65_536
    rate_limit_auth_per_minute: int = 20
    rate_limit_ingest_per_minute: int = 120
    rate_limit_investigation_per_minute: int = 30
    hmac_replay_window_seconds: int = 300

    @model_validator(mode="after")
    def set_database_url(self):
        if not self.database_url:
            env_url = os.getenv("DATABASE_URL")
            if env_url:
                self.database_url = env_url
            elif os.getenv("POSTGRES_HOST") or os.getenv("POSTGRES_DB"):
                self.database_url = (
                    f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}@"
                    f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
                )
            else:
                self.database_url = "sqlite:///./consenttrace.db"

        if not self.app_mode:
            if self.app_env.strip().upper() == "PRODUCTION":
                self.app_mode = "PRODUCTION"
            elif self.sandbox_enabled:
                self.app_mode = "SANDBOX"
            else:
                self.app_mode = "DEMO"
        self.app_mode = self.app_mode.strip().upper()
        if self.app_mode not in {"DEMO", "SANDBOX", "PRODUCTION"}:
            raise ValueError("APP_MODE must be DEMO, SANDBOX, or PRODUCTION.")
        if self.app_mode == "PRODUCTION":
            if self.sandbox_enabled:
                raise ValueError("SANDBOX_ENABLED must be false in PRODUCTION mode.")
            if self.database_url.startswith("sqlite"):
                raise ValueError("PRODUCTION mode requires PostgreSQL.")
            if len(self.api_key_pepper) < 32 or self.api_key_pepper == "local-development-only-api-key-pepper":
                raise ValueError("PRODUCTION mode requires a dedicated API_KEY_PEPPER of at least 32 characters.")
            if self.api_key_encryption_key == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=":
                raise ValueError("PRODUCTION mode cannot use the local development API key encryption key.")
            try:
                encryption_key = base64.urlsafe_b64decode(self.api_key_encryption_key)
            except Exception as exc:
                raise ValueError("PRODUCTION mode requires a valid API_KEY_ENCRYPTION_KEY.") from exc
            if len(encryption_key) != 32:
                raise ValueError("API_KEY_ENCRYPTION_KEY must decode to exactly 32 bytes.")
            if self.dev_bootstrap_api_key or self.sandbox_connector_api_key or self.sandbox_admin_api_key:
                raise ValueError("Development bootstrap keys cannot be configured in PRODUCTION mode.")
            if bool(self.production_admin_api_key) != bool(self.production_admin_org_id):
                raise ValueError("PRODUCTION_ADMIN_API_KEY and PRODUCTION_ADMIN_ORG_ID must be configured together.")
        if self.max_json_body_bytes < 1 or self.max_ingestion_event_bytes < 1 or self.max_evidence_payload_bytes < 1:
            raise ValueError("Request body limits must be positive.")
        return self

    class Config:
        env_file = BASE_DIR.parent / ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
