# Hermes Workspace compatibility

## Why this patch exists

Hermes Workspace expects a FastAPI backend exposed by `hermes webapi`.

Upstream `NousResearch/hermes-agent` currently does not ship that backend. The WebAPI layer was ported from `outsourc-e/hermes-agent` into this fork so Workspace can use:

- health checks
- chat streaming
- session CRUD
- memory browsing
- skills browsing
- config reads and writes

## Ported WebAPI commits

These commits were cherry-picked from `outsourc-e/hermes-agent` onto this fork:

- `c941ae7f` feat: Hermes Web API — FastAPI backend with session CRUD, SSE chat streaming, memory, skills, config endpoints
- `14ed6909` fix: webapi deps — fallback for missing gateway._resolve_model import
- `10484330` fix: webapi package discovery + entry point, auto port detection, codex auth auto-sync
- `393989de` fix: preserve multipart image content in Codex Responses API conversion
- `8c4500b4` feat: image attachment support in WebAPI — ChatAttachment model + multipart content builder
- `bb43bd38` fix: preserve multipart content in _preflight_codex_input_items — was re-stringifying image data
- `51827704` fix: CORS covers localhost:3000-3010 by default, configurable via HERMES_CORS_ORIGINS
- `c82ba9f5` feat: PATCH /api/config — write model/provider/base_url to ~/.hermes/config.yaml
- `095cf5af` feat: GET /api/available-models — returns provider model catalog + auth status

## Primary files touched

- `webapi/__init__.py`
- `webapi/__main__.py`
- `webapi/app.py`
- `webapi/deps.py`
- `webapi/errors.py`
- `webapi/models/*`
- `webapi/routes/*`
- `webapi/sse.py`
- `pyproject.toml`
- `run_agent.py`
- `hermes_cli/auth.py`

## Required Workspace endpoints

At minimum, Hermes Workspace depends on these routes behaving:

- `GET /health`
- `GET /v1/models`
- `GET /api/available-models`
- `GET /api/sessions`
- `POST /api/sessions`
- `GET /api/sessions/{session_id}/messages`
- `POST /api/sessions/{session_id}/chat`
- `GET /api/memory`
- `GET /api/skills`
- `GET /api/config`
- `PATCH /api/config`

## Smoke test

### Boot the backend

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e .
hermes-webapi
```

### Check core routes

```bash
curl http://localhost:8642/health
curl http://localhost:8642/v1/models
curl http://localhost:8642/api/available-models
curl http://localhost:8642/api/sessions
curl http://localhost:8642/api/skills
curl http://localhost:8642/api/memory
curl http://localhost:8642/api/config
```

### Workspace manual checks

In Hermes Workspace verify:

- app loads
- backend connects
- can create or load a session
- chat streams
- memory pane loads
- skills pane loads
- settings page can read model config

## Conflict rules on upstream updates

When upstream touches patched files:

- preserve the Workspace API contract first
- prefer upstream behavior where it does not break the API contract
- keep `run_agent.py` edits as small as possible
- if upstream introduces a cleaner extension point, migrate to it and reduce the diff

## Known note

One cherry-picked commit introduced `AUDIT-REPORT.md` from the source fork. That file is not part of the compatibility contract and can be dropped later if it becomes noise.
