# ATOM DATA FOUNDRY – React frontend

React + TypeScript + Vite + Tailwind CSS + React Flow + TanStack Query + Recharts, built from BRD v4.0.

## Run

```bash
npm install
npm run dev        # http://localhost:5173
npm run build
npx tsx scripts/smoke.ts   # headless check of the demo engine (all 3 modes, exports, load)
```

## Journey (routes)

| Route | BRD step |
| --- | --- |
| `/connect` | 1–2 Connect database, Test Connection, Boomi Process A progress |
| `/schema` | 3 Schema graph (React Flow), field/key/relationship detail, manual fields for MongoDB collections without validators |
| `/mode` | 4 Fast Test / AI Realistic & Scenario / AI Test Case Generator inputs |
| `/generate` | 5 Job progress and AI blueprint |
| `/preview` | 6 Paginated previews, nine validation checks, scenario coverage + *Generate missing scenarios*, test cases + linked prerequisite records |
| `/output` | 7 Excel, CSV ZIP, JSON, SQL, test-case workbook, Postman, Pytest, mapping report, reports, DB-load confirmation |
| `/result` | 8 Downloads, Boomi Process B load report, test-readiness report |
| `/how-it-works` | Architecture and ownership summary |

## Backend

By default `src/api/mock/*` runs a real in-browser engine (dependency ordering, FK-consistent generation, validators, exporters) so every screen works offline.
Set `VITE_API_BASE` (see `.env.example`) to use FastAPI; the REST contract is `src/api/httpApi.ts` and the typed interface is `src/api/types.ts`.

Security: passwords/URIs are only used for the connection test and cleared afterwards; schema and load requests carry a target id, never credentials.
