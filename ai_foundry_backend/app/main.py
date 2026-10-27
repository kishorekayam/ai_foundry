from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import ai, boomi_client
from .config import get_settings
from .routers import internal, public

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="ATOM DATA FOUNDRY API", version="1.0.0")
s = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Client-Id"], expose_headers=["Content-Disposition"])
app.include_router(public.router)
app.include_router(internal.router)


@app.on_event("startup")
def _prepare_registry() -> None:
    """Create / migrate the registry tables (idempotent) so a new release never meets an old table layout."""
    from . import registry

    if registry.enabled():
        try:
            registry.init_schema()
        except Exception as e:  # keep the API up; the registry error will surface per request
            logging.getLogger("atom").error("registry init failed: %s", e.__class__.__name__)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    logging.getLogger("atom").exception("unhandled error")
    return JSONResponse({"detail": "Internal error. Check the server log."}, status_code=500)


@app.get("/health")
def health():
    return {"status": "ok", "boomi": "configured" if boomi_client.configured() else "direct-mode", "ai": "openai" if ai.available() else "rules-only"}
