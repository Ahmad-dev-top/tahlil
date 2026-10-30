# Tahlil — Project Plan

**What it is:** an autonomous data-analyst agent. Users upload a CSV or connect a database, ask questions in plain English, and get back SQL, a result table, a chart and a short report. Every query is safety-checked, all generated code runs in a Docker sandbox, and every number in the report is verified against the real results.

**Why it matters (portfolio/freelance):** it shows production agent engineering (LangGraph control flow, CrewAI roles, GuardrailsAI validation, sandboxed execution, evals, CI) plus a modern React frontend, in a product any business understands.

**Workflow:** Claude writes the code → **Cursor integrates, runs, fixes and verifies** each phase using the prompts below. Cursor follows `.cursor/rules/tahlil.mdc`.

---

## Status at a glance

| # | Phase | Code | Verified here | Cursor must |
|---|---|---|---|---|
| 0 | Core agent (graph, guards, sandbox, crew, API) | ✅ | ✅ tests, Docker sandbox, one live question | — |
| 1 | Streaming (`/ask/stream`, SSE) | ✅ | ✅ tests + live SSE (steps over time, result matches `/ask`, 404, error event) | — |
| 2 | Conversations & follow-up questions | ✅ | ✅ tests + live follow-ups (region, then WhatsApp, then Q1–Q4) | — |
| 3 | Database connectors (Postgres/MySQL snapshot) | ✅ | ✅ Postgres + MySQL seed, live connector tests, API connect/refresh/safety, live Punjab question on the snapshot | — |
| 4 | Web UI: Next.js 16 + React 19 + Tailwind 4 | ✅ | ✅ typecheck, lint, unit, build, browser e2e, live Haiku UI (5 questions) | — |
| 5 | Auth (API keys) + rate limiting | ✅ | ✅ tests | — |
| 6 | Evals (accuracy on known answers) | ✅ | ✅ 23 questions; Haiku + CrewAI 100% accuracy and verified | — |
| 7 | CI (GitHub Actions) | ✅ | ✅ backend, sandbox-docker, frontend, and e2e green on main | — |
| 8 | Deployment (compose + nginx, Oracle Cloud) | ✅ | ✅ https://tahlil.muhammad-dgr.duckdns.org (Let's Encrypt, portfolio still up) | — |
| 9 | Portfolio packaging | ✅ | ✅ GIF, three stills, case study, Upwork offer, LinkedIn post | — |

Tests: **69 backend tests** (`pytest -q`, plus 2 live DB tests skipped unless `TAHLIL_LIVE_DB=1`), **8 frontend unit tests** (`npm test`) and a **browser e2e test** (`npm run test:e2e`) that uploads a CSV, watches the steps stream in, checks the answer, asks a follow-up, stops a run, checks the unreachable state, and checks the mobile layout. The default backend suite passes with no API key or Docker.

**Verified locally:** `pytest -q` is 69 passed, 2 skipped. With `TAHLIL_LIVE_DB=1` the two connector tests run as well. Also verified: the 23-question eval matrix (see the README), live sonnet questions including Punjab on the Postgres snapshot, frontend typecheck/lint/build/e2e, and five live Haiku questions in the web UI. GitHub CI on `main` is green: https://github.com/Ahmad-dev-top/tahlil/actions/runs/41064093674. The weekly evals workflow has run on the tuning set at 100%.

**Deployed:** `https://tahlil.muhammad-dgr.duckdns.org` on the existing portfolio VM (Ubuntu 22.04, x86_64, host nginx + certbot). The API is on `127.0.0.1:18000` because `/opt/dogar` already uses `127.0.0.1:8000`. Caddy is not running. The app directory is a git checkout of this repo at `/home/ubuntu/tahlil`. Updates are `git pull && docker compose up -d --build`.

---

## Architecture

```
Next.js static app ──HTTP/SSE──► nginx (/api proxy, injects API key)
                               │
                               ▼
                      FastAPI (app/api.py) ── auth, rate limit, SSE
                               │
              ┌────────────────┼──────────────────────────┐
              ▼                ▼                          ▼
     store.py (SQLite)   graph.py (LangGraph)      connectors.py
     datasets, chats,         │                    Postgres/MySQL ──► snapshot
     turns                    │                                        │
                              ▼                                        ▼
   load_schema → plan → write_sql → guard_sql ─► run_sql ─► analyze ─► report ─► guard_report → finish
                    ▲          ▲  (GuardrailsAI)    │ DuckDB    │ Docker   │ CrewAI   │ GuardrailsAI
                    │          └──── retry with ────┘ read-only │ sandbox  │ crew     │ (grounded numbers)
           conversation history      validator/DB error                    └── retry ─┘
```

| File | Responsibility |
|---|---|
| `app/graph.py` | LangGraph state machine, routing, retries, `ask()` and `stream()` |
| `app/guards.py` | GuardrailsAI validators: `ReadOnlySQL`, `GroundedNumbers` |
| `app/sandbox.py` + `sandbox/` | Runs agent Python in a locked-down container |
| `app/crew.py` | CrewAI Insight Analyst + Report Writer |
| `app/db.py` | DuckDB datasets (CSV or DataFrames), read-only queries |
| `app/connectors.py` | SQLAlchemy snapshot import from Postgres/MySQL |
| `app/store.py` | SQLite metadata: datasets, conversations, turns |
| `app/api.py` | FastAPI routes, auth, rate limit, SSE |
| `app/llm.py` | litellm client + scripted `FakeLLM` for tests |
| `frontend/` | Next.js + React + Tailwind web app (static export, served by nginx) |
| `evals/` | Question set + scorer |

---

## Phase 0 — Core agent ✅

Done: everything in the table above except the frontend.

**Cursor prompt:**
> Read PLAN.md and .cursor/rules/tahlil.mdc. Create a venv, `pip install -r requirements.txt pytest`, run `pytest -q` and confirm 46 pass. Then build the sandbox image (`docker build -t tahlil-sandbox:latest sandbox`) and run `TEST_SANDBOX_MODE=docker pytest -q tests/test_graph.py`. Fix anything that fails in Docker mode without weakening the container flags in app/sandbox.py. Finally copy .env.example to .env, add my ANTHROPIC_API_KEY, run `uvicorn app.api:app --reload`, upload sample_data/sales.csv via /docs and ask "Which region brings the most revenue?". Show me the response JSON.

**Done when:** tests green in local and Docker mode; one live question returns `status: ok`, a chart and `verified: true`.

---

## Phase 1 — Streaming ✅

`POST /ask/stream` returns Server-Sent Events: one `step` event per graph node as it finishes, then `result` (same JSON as `/ask`) or `error`.

```
event: step
data: {"step": "guard_sql", "passed": false, "errors": ["Only SELECT queries are allowed (got Drop)."]}
```

No Cursor work needed beyond Phase 0. Manual check: `curl -N -X POST localhost:8000/ask/stream -H 'content-type: application/json' -d '{"dataset_id":"…","question":"…"}'`

---

## Phase 2 — Conversations ✅

- `POST /conversations {dataset_id}` → `GET /conversations/{id}` returns turns.
- `/ask` and `/ask/stream` accept `conversation_id`. The last 5 successful turns (question, SQL, answer excerpt) are fed to the planner and SQL writer, so "now only Punjab" works.
- The first question becomes the conversation title.

**Cursor prompt (live check):**
> With the API running on a live model, create a conversation on the sales dataset, ask "Revenue by region", then "Now only for the WhatsApp channel". Confirm the second SQL keeps the region grouping and adds the channel filter. If it doesn't, improve the history instructions in app/prompts.py (not the guards) and re-run.

---

## Phase 3 — Database connectors ✅

`POST /datasets/connect {url, schema?, tables?, row_limit?, name?}` copies tables into a DuckDB snapshot. The agent never queries the source DB. `POST /datasets/{id}/refresh` re-imports.

Safety: only `postgresql` / `mysql` / `mariadb` URLs; SQLite is blocked unless `ALLOW_SQLITE_CONNECTOR=true` (SQLite URLs are server file paths); optional `CONNECTOR_ALLOWED_HOSTS`; Postgres sessions forced read-only; the stored label never contains the password; row and table caps.

**Cursor prompt:**
> Start Postgres and MySQL with docker (`postgres:16`, `mysql:8`). Load sample_data/sales.csv into a `sales` table in both (write a small script in scripts/seed_dbs.py). Add an integration test file tests/test_connectors_live.py, skipped unless env `TAHLIL_LIVE_DB=1`, that imports from both via `import_database` using URLs `postgresql+psycopg://…` and `mysql+pymysql://…`, then asks a question through `graph.ask` with a FakeLLM. Also verify a Postgres non-public schema works with `schema=`. Fix any type issues (dates, decimals) in app/connectors.py by converting columns, never by loosening validation.

**Done when:** both DBs import; Decimal/date columns arrive as numeric/date types in DuckDB; the live test passes.

**Known limitation (accepted for v1):** refresh needs the URL again because credentials are not stored. A later version could store them encrypted.

---

## Phase 4 — Web UI (Next.js + React + Tailwind) ✅

Stack: **Next.js 16** (App Router, static export) · **React 19** · **Tailwind CSS 4** (+ typography) · TypeScript · `react-markdown` · `lucide-react` · Vitest · Playwright.

Layout: sidebar (upload CSV, connect DB, datasets, conversations) + chat. Each answer shows live step chips as the agent works (a rejected and retried query is visible), a **Numbers verified** badge, the markdown report, the chart, and expandable Data / SQL / Plan / Computed stats sections. Below 1024 px the sidebar becomes a drawer. Dark mode follows the system.

| File | Purpose |
|---|---|
| `src/lib/api.ts` | REST client + `askStream()` async generator over `fetch` streaming |
| `src/lib/sse.ts` | Incremental SSE parser (unit-tested, handles split chunks/CRLF) |
| `src/lib/steps.ts` | Trace entry → label/ok/detail (add a case when adding a graph node) |
| `src/lib/format.ts` | Table cell formatting |
| `src/lib/types.ts` | API types |
| `src/hooks/useTahlil.ts` | All app state + actions in one hook (no state library) |
| `src/components/*` | App shell, Sidebar, ConnectDialog, ChatView, TurnCard, StepTimeline, ResultTable |
| `e2e/smoke.cjs` | Playwright browser test |
| `Dockerfile` + `nginx.conf.template` | Static build served by nginx, `/api` proxied with the key injected server-side |

Why a static export: the app is fully client-side, so production needs no Node server. nginx serves the files, proxies `/api` and keeps the API key out of the browser.

**Verified here:** `tsc`, ESLint, 7 unit tests, `next build`, and the e2e test in Chromium against the real backend. The test checked that steps arrived one at a time (step counts 0→1→2→5→…→8), the verified badge, the data table, the SQL, a follow-up question, the sidebar title, and that a 390 px mobile layout has no horizontal overflow.

**Cursor prompt:**
> cd frontend, `npm ci`, run `npm run typecheck && npm run lint && npm test && npm run build`. Start the backend with a LIVE model (`uvicorn app.api:app`) and `npm run dev`, upload sample_data/sales.csv and ask 5 real questions. Fix any UI issues with real reports (long markdown, tables, multiple charts, unverified answers, failed questions). Then: (1) add a "Stop" button that aborts the stream (useTahlil already keeps an AbortController), (2) show the rejected SQL in the step chip tooltip on hover, (3) add an empty/error state when the API is unreachable, with a retry button. Keep `npm run test:e2e` passing and extend it for the new features.

**Done when:** all checks green, 5 live questions render well on desktop and mobile, and the Stop button works.

---

## Phase 5 — Auth & rate limiting ✅

- `API_KEYS` (comma-separated). If set, every route except `/health` and `/charts/*` needs `X-API-Key`. Chart URLs contain ~88 random bits, so they are left open for `<img>` tags.
- Per-caller sliding-window limit on `/ask` and `/ask/stream` (`ASKS_PER_MINUTE`, default 10).

**Limits to know:** the limiter is in-memory (one API process). Behind the nginx proxy every user shares one key, so the limit is effectively global. For multi-user production, add per-user accounts and Redis-backed limits (backlog).

---

## Phase 6 — Evals ✅

`evals/questions.json` holds 23 questions: 20 numeric, with reference SQL, and 3 the schema cannot answer. `python -m evals.run` scores each one and saves accuracy, verified rate, first-try report rate, latency percentiles, cost, and per-step `duration_ms` to `evals/results/`.

**Cursor prompt:**
> Build the sandbox image and run `python -m evals.run` with my live model. For each failure, read the saved SQL and reason, then improve app/prompts.py (planner/SQL/analysis prompts) to fix the pattern, not the specific question. Never change the guards or the scorer to make a question pass. Re-run until accuracy ≥ 80% and verified rate ≥ 80%. Then add 10 harder questions (multi-step, window functions, ambiguous wording) with reference SQL and report the new score. Compare two models (e.g. claude-sonnet and a cheaper one) and add a results table to README.md.

**Done when:** ≥ 80% accuracy and ≥ 80% verified on a Haiku config, with a results table in the README. Met on the tuning set (100% / 100% for both Haiku configs). A later 10-question holdout, with no prompt changes, scored 90%. Three tuning-set repeats stayed at 100% accuracy and 100% verified. `.env.example` now defaults to Haiku 5.5 with CrewAI on.

---

## Phase 7 — CI ✅

`.github/workflows/ci.yml` runs on every push and pull request:
1. `backend`: pytest
2. `sandbox-docker`: builds the sandbox image and runs the graph tests inside real containers
3. `frontend`: typecheck, lint, unit tests, static build
4. `e2e`: Playwright browser test against the real backend (offline model), screenshots uploaded as an artifact

`.github/workflows/evals.yml` is the live accuracy check. It runs on `workflow_dispatch` and weekly (`0 3 * * 1`), not on every push. Its steps are skipped when the `ANTHROPIC_API_KEY` repo secret is missing.

**Cursor prompt:**
> git init, commit, create a GitHub repo `Ahmad-dev-top/tahlil` and push. Make every CI job green. Add the CI badge to README.md.

---

## Phase 8 — Deployment ✅ live at https://tahlil.muhammad-dgr.duckdns.org

`docker compose up -d --build` starts:
- `sandbox-image`: builds the sandbox image, then exits (`restart: "no"`, because `command: true` would loop)
- `api`: bound to 127.0.0.1:8000, mounts docker.sock to launch sandbox containers
- `web`: nginx on 127.0.0.1:8080, serving the Next.js static export and proxying `/api` (adds the API key server-side; SSE buffering off)
- `caddy` (profile `https` only): automatic HTTPS when 80/443 are free

Public demo (`PUBLIC_DEMO=true`): no `/datasets/connect` or refresh, 5 MB and 3 files, sample CSV preloaded, daily USD cap, rate limit per client IP. `X-Forwarded-For` is trusted only from `TRUSTED_PROXIES` (compose sets `web`).

Live steps, the server `.env`, and the "existing proxy vs Caddy" choice are in `deploy/README.md`. Do not start Caddy if the portfolio already owns 80/443. Port 8000 stays on loopback.

**Cursor prompt:**
> Add a Caddy service to docker-compose.yml (caddy:2) that serves HTTPS for the domain in env `TAHLIL_DOMAIN` and reverse-proxies to `web:80`. Move `web` off public port 80. Add optional basic auth via env `TAHLIL_BASIC_AUTH` (bcrypt hash). Document it in README under "Deploy". Test locally with `TAHLIL_DOMAIN=localhost`.

**Note:** mounting docker.sock gives the API container control of the host's Docker. That's standard for this pattern, but keep the API off the public internet (only nginx is public) and keep `--network none` on sandboxes. For stronger isolation later, run the sandbox under gVisor (`--runtime=runsc`).

---

## Phase 9 — Portfolio packaging ✅

- README hero: one-line pitch, live demo, `docs/demo.gif` (~25s), four bullets, then the architecture diagram.
- Stills: `docs/desktop-answer.png`, `docs/mobile.png`, `docs/trace.png`. The live region question passed the SQL guard on the first try, so the trace still is that path.
- `docs/case-study.md`, `docs/upwork-offer.md`, `docs/linkedin-post.md`.
- Public demo is the sample dataset, with connect/refresh disabled. No basic auth; the daily cost cap and the one-question gate are the limits.

---

## Backlog (after v1)

- Store DB credentials encrypted (Fernet + key from env) so refresh needs no URL
- Excel (.xlsx) and Parquet upload
- Multi-user accounts, per-user datasets, Redis rate limits
- Interactive charts (return a Vega-Lite spec alongside the PNG)
- Token/cost tracking per question in the trace
- Scheduled reports ("every Monday, email me revenue by region")
- gVisor runtime for the sandbox

---

## Commands

```bash
# backend dev (no key, no Docker)
pip install -r requirements.txt pytest
LLM_MODE=fake SANDBOX_MODE=local uvicorn app.api:app --reload
pytest -q

# real sandbox
docker build -t tahlil-sandbox:latest sandbox
TEST_SANDBOX_MODE=docker pytest -q tests/test_graph.py

# frontend dev (talks to http://localhost:8000, see frontend/.env.development)
cd frontend && npm install && npm run dev            # http://localhost:3000
npm run typecheck && npm run lint && npm test && npm run build

# browser e2e (backend: LLM_MODE=fake SANDBOX_MODE=local DEMO_DELAY_S=0.4 uvicorn app.api:app)
npx playwright install chromium && npm run test:e2e

# evals
python -m evals.run --fake          # harness self-test
python -m evals.run                 # live model

# everything
docker compose up --build           # http://localhost
```
