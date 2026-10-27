# ATOM DATA FOUNDRY – FastAPI backend

Python 3.12 · FastAPI · SQLAlchemy · Faker · NumPy · NetworkX · openpyxl · Gemini (optional)

## Run

```bash
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python scripts\dev_demo.py      # API on :8000 with a throw-away embedded PostgreSQL, no credentials needed
.venv\Scripts\python -m pytest -q             # end-to-end tests against a real PostgreSQL (embedded)
```

Frontend: set `VITE_API_BASE=http://localhost:8000` in `ai_foundry_frontend/.env.local`.

For your own PostgreSQL: copy `targets.example.json` → `targets.json`, `.env.example` → `.env`, then run
`scripts/seed_placement_db.py` (creates the empty test schema and an app user).

## Layout

| Path | Role |
| --- | --- |
| `app/routers/public.py` | REST API used by React (`/api/*`) |
| `app/routers/internal.py` | Callbacks Boomi calls (`/internal/*`, `X-Internal-Secret`) |
| `app/boomi_client.py` | Calls Boomi Process A (metadata) and B (load) |
| `app/metadata/` | Approved metadata SQL, PyMongo adapter, normalizer |
| `app/engine/` | Generator, validator, planners, exporters, pipeline |
| `app/ai.py` | OpenAI (gpt-4o) blueprint/test-plan with Pydantic validation, rule-based fallback |
| `app/loader.py` | Parameterized batch inserts (parents first) + verification |

## Modes

* `BOOMI_ENABLED=false` → **direct mode**: Python reads metadata and loads itself (flagged in the schema warnings).
* `BOOMI_ENABLED=true` (+ `SERVER_BASE_URL`) → metadata via Boomi Process A, loads via Boomi Process B, which call back `/internal/*`.
* `OPENAI_API_KEY` empty → rule-based planners; set → GPT-4o plans, Python validates.

## Registry + Boomi setup (done once)

```bash
.venv\Scripts\python scripts
egistry_admin.py genkey   # REGISTRY_ENCRYPTION_KEY into .env (back it up)
.venv\Scripts\python scripts
egistry_admin.py init     # needs MYSQL_* and MYSQL_SSL_CA (verified TLS) in .env
```

Users add their own databases from the UI; they are stored encrypted in `registered_targets` and shown only to the browser that saved them.
Boomi Process A/B (folder `AtomFoundry-SchemaAndLoad`) call `/internal/*` here. Start the API with `BOOMI_ENABLED=true` to route through them.

## Authentication

Every API (`/api/*` and `/internal/*`) requires HTTP Basic with `API_USERNAME` / `API_PASSWORD`; only `/health` is open.
The same pair is used by the React sign-in form, by the Boomi REST connection (`AF FastAPI Internal`) and by FastAPI when it calls the Boomi listeners.
Boomi listeners are enforced by the runtime's Shared Web Server port: set its authentication type to Basic and add a user with these credentials.
