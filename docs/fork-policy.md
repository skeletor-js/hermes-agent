# Hermes Agent Fork Operating Policy

## Purpose

Maintain a stable internal fork of `NousResearch/hermes-agent` that includes:

- Hermes Workspace WebAPI support
- Superbud supermemory hook assets

Without:

- relying on third-party forks
- reapplying local hacks by hand
- pulling upstream changes blindly

## Repo model

- upstream: `NousResearch/hermes-agent`
- fork: `skeletor-js/hermes-agent`
- deploy branch: `main`

`main` is the branch we actually run. It should always be:

- upstream-compatible
- Workspace-compatible
- supermemory-compatible
- stable enough to trust

## What belongs in this fork

Allowed:

- WebAPI support required by Hermes Workspace
- supermemory hook assets and deployment scripts
- docs and smoke-test scripts needed to maintain the fork

Not allowed:

- unrelated experiments
- convenience hacks with no runtime value
- speculative features
- broad customizations with no clear Workspace or ops value

Rule: if a change does not support Workspace, supermemory, or maintainability, it probably does not belong.

## Branch policy

Keep it simple.

- `main` = stable patched branch
- temporary branches only for update work or patch work

Examples:

- `update/upstream-2026-03-21`
- `feat/webapi-port`
- `feat/supermemory-hooks`

No permanent integration branch.

## Patch structure

### Patch A
Workspace WebAPI compatibility.

Current sources ported from `outsourc-e/hermes-agent` include:

- `webapi/`
- `pyproject.toml`
- `run_agent.py`
- `hermes_cli/auth.py`

### Patch B
Supermemory hook assets.

Current tracked assets live under:

- `deploy/hooks/superbud-memory/`
- `scripts/install-superbud-hook.sh`

## Update policy

Default cadence:

- update from upstream once per week at most
- skip weeks where nothing important landed
- do off-cycle updates only for fixes we actually need

We do not:

- merge upstream daily
- auto-sync with upstream
- update just because upstream moved

We do:

- pull upstream when there is a reason:
  - bugfix we need
  - security fix
  - provider/model fix we care about
  - feature we actually want

This is a curated runtime branch, not a mirror.

## Standard update workflow

### 1. Fetch upstream

```bash
git fetch upstream
```

### 2. Create update branch

```bash
git checkout main
git pull origin main
git checkout -b update/upstream-YYYY-MM-DD
```

### 3. Merge upstream main

```bash
git merge upstream/main
```

### 4. Resolve conflicts

Priority order:

1. preserve upstream behavior where possible
2. preserve WebAPI compatibility
3. preserve supermemory hook compatibility
4. avoid inventing new logic during conflict resolution

### 5. Run verification

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e .
bash scripts/smoke-test-webapi.sh
bash scripts/install-superbud-hook.sh --check
```

Then manually verify Hermes Workspace:

- app loads
- backend connects
- can start or load a chat
- sessions view works
- memory view works
- skills view works

### 6. Promote if clean

```bash
git checkout main
git merge update/upstream-YYYY-MM-DD
git push origin main
```

### 7. Delete temp branch

```bash
git branch -d update/upstream-YYYY-MM-DD
```

## Urgent fix workflow

If upstream ships one fix we need right now, do not merge a pile of unrelated commits.

```bash
git checkout main
git pull origin main
git checkout -b hotfix/cherry-pick-topic
git cherry-pick <commit_sha>
```

Run smoke tests, then merge back to `main` if clean.

## Smoke test policy

Every upstream merge or cherry-pick must pass:

- `pip install -e .`
- `bash scripts/smoke-test-webapi.sh`
- Hermes Workspace manual smoke test
- `bash scripts/install-superbud-hook.sh --check`

If any fail, the update is not complete.

## Long-term objective

This is not meant to become a forever-fork monster.

The goal is to keep a thin internal patchset until:

- upstream supports the needed WebAPI officially
- the supermemory hook deployment is standardized enough to be boring
- our custom delta shrinks instead of grows

## One-sentence principle

This fork is a stable, minimal compatibility layer on top of upstream Hermes Agent, not a second product.
