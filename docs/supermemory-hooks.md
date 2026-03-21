# Supermemory hook assets

## Goal

Track the Superbud supermemory hook in git so its logic stops living as an unversioned local snowflake.

The live runtime hook currently exists at:

- `~/.hermes/hooks/superbud-memory/`

This fork now tracks a copy at:

- `deploy/hooks/superbud-memory/`

That makes hook changes reviewable and keeps them from being manually re-applied after backend updates or machine changes.

## What the hook does

Current hook behavior, based on the tracked handler:

- `agent:start`
  - extract entities from the incoming message
  - search Supermemory
  - write a briefing file
  - inject a pointer into `MEMORY.md`

- `agent:end`
  - extract facts and decisions from the latest exchange via a cheap LLM
  - save them to Supermemory with debounce logic

- `session:end`
  - generate and save a full session summary

## Tracked files

- `deploy/hooks/superbud-memory/HOOK.yaml`
- `deploy/hooks/superbud-memory/handler.py`

Intentionally not tracked:

- `state.json`
- `entities.json`
- `__pycache__/`

Those are runtime state, not source.

## Deploying the tracked hook

Use:

```bash
bash scripts/install-superbud-hook.sh
```

That copies the tracked hook files into `~/.hermes/hooks/superbud-memory/` without overwriting runtime state files.

## Verifying the hook

### Check installation

```bash
bash scripts/install-superbud-hook.sh --check
```

### Verify runtime behavior

Confirm:

- `~/.hermes/hooks/superbud-memory/HOOK.yaml` exists
- `~/.hermes/hooks/superbud-memory/handler.py` matches the tracked version
- hook still fires on `agent:start`, `agent:end`, and `session:end`
- `~/.hermes/supermemory_briefing.md` is updated when relevant
- no hook crash appears in gateway logs

## Update policy

When changing the hook:

1. edit the tracked version in `deploy/hooks/superbud-memory/`
2. run `bash scripts/install-superbud-hook.sh`
3. test on a real conversation
4. commit the tracked source change

Do not treat the live `~/.hermes/hooks/...` directory as the source of truth forever. That is how drift starts.

## Strategic note

This hook is still operationally coupled to the local Hermes runtime rather than the repo itself. Tracking it in this fork fixes versioning and repeatability, but if we want zero drift long-term we should either:

- formalize these hooks as first-class repo assets with a proper deploy step, or
- upstream the hook deployment pattern into our own install flow
