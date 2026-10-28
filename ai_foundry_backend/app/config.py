# app/config.py
"""Runtime configuration. Everything comes from environment variables (or a .env file in the backend folder)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Settings(BaseModel):
    cors_origins: list[str]
    api_username: str
    api_password: str
    targets_file: Path
    data_dir: Path
    # Common registry database (MySQL): approved targets + encrypted credentials + Boomi audit trail
    registry_url: str
    registry_key: str
    registry_ssl_ca: str
    allow_private_targets: bool
    max_targets_per_owner: int
    # Boomi runtime shared web server (the listeners of Process A / B). BOOMI_ENABLED=false = direct mode.
    boomi_enabled: bool
    boomi_base_url: str
    boomi_auth_type: str
    boomi_username: str
    boomi_token: str
    boomi_bearer: str
    boomi_metadata_path: str
    boomi_load_path: str
    boomi_verify_ssl: bool
    # Hosted LLM (OpenAI)
    openai_api_key: str
    openai_model: str
    openai_base_url: str
    # Public URL of this API as seen by Boomi (used only for documentation / health output)
    public_base_url: str


def _registry_url(e) -> str:
    if e("REGISTRY_DB_URL"):
        return e("REGISTRY_DB_URL")
    if not e("MYSQL_HOST"):
        return ""
    from urllib.parse import quote_plus

    return f"mysql+pymysql://{quote_plus(e('MYSQL_USER', 'root'))}:{quote_plus(e('MYSQL_PASSWORD', ''))}@{e('MYSQL_HOST')}:{e('MYSQL_PORT', '3306')}/{e('MYSQL_DATABASE', 'atom_registry')}"


@lru_cache
def get_settings() -> Settings:
    _load_dotenv()
    e = os.environ.get
    return Settings(
        cors_origins=[o.strip() for o in e("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()],
        api_username=e("API_USERNAME", ""),
        api_password=e("API_PASSWORD", ""),
        targets_file=Path(e("TARGETS_FILE", str(ROOT / "targets.json"))),
        data_dir=Path(e("DATA_DIR", str(ROOT / "data"))),
        registry_url=_registry_url(e),
        registry_key=e("REGISTRY_ENCRYPTION_KEY", ""),
        registry_ssl_ca=e("MYSQL_SSL_CA", ""),
        allow_private_targets=e("ALLOW_PRIVATE_TARGETS", "false").lower() == "true",
        max_targets_per_owner=int(e("MAX_TARGETS_PER_OWNER", "10")),
        boomi_enabled=e("BOOMI_ENABLED", "false").lower() == "true",
        boomi_base_url=e("SERVER_BASE_URL", "").rstrip("/"),
        boomi_auth_type=e("SERVER_AUTH_TYPE", "basic").lower(),  # basic sends API_USERNAME/API_PASSWORD to the Boomi listeners
        boomi_username=e("SERVER_USERNAME", "") or e("API_USERNAME", ""),
        boomi_token=e("SERVER_TOKEN", "") or e("API_PASSWORD", ""),
        boomi_bearer=e("SERVER_BEARER_TOKEN", ""),
        boomi_metadata_path=e("BOOMI_METADATA_PATH", "/ws/simple/executeAfmetadata"),
        boomi_load_path=e("BOOMI_LOAD_PATH", "/ws/simple/executeAfload"),
        boomi_verify_ssl=e("SERVER_VERIFY_SSL", "true").lower() != "false",
        openai_api_key=e("OPENAI_API_KEY", ""),
        openai_model=e("OPENAI_MODEL", "gpt-4o"),
        openai_base_url=e("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        public_base_url=e("PUBLIC_BASE_URL", "http://localhost:8000"),
    )
