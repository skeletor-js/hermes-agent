# Weekly curated update checklist

Use this fork policy for upstream Hermes Agent updates.

## Rule

Do not merge upstream just because it moved.

Only sync when:

- there is a fix we care about
- there is a security or reliability reason
- there is a model/provider improvement we actually want

## Fast path

```bash
bash scripts/weekly-upstream-sync.sh
```

That will:

- fetch `origin` and `upstream`
- update local `main`
- create `update/upstream-YYYY-MM-DD`
- merge `upstream/main` into that branch
- stop before promotion

## Required verification

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e .
bash scripts/install-superbud-hook.sh --check
hermes webapi --port 8652
HERMES_API_URL=http://127.0.0.1:8652 bash scripts/smoke-test-webapi.sh
```

Then manually verify Hermes Workspace:

- loads successfully
- can open a session
- can chat
- session list works
- memory view works
- skills view works

## Promote if clean

```bash
git checkout main
git merge update/upstream-YYYY-MM-DD
git push origin main
```

## Emergency cherry-pick path

If upstream has one urgent fix and we do not want the whole merge:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b hotfix/<topic>
git cherry-pick <commit_sha>
```

Then run the same verification steps.

## Notes

- Active runtime repo: `/home/jordan/.local/share/hermes-agent`
- Source repo clone: `/home/jordan/src/hermes-agent`
- Canonical fork remote: `skeletor-js/hermes-agent`
- Upstream remote: `NousResearch/hermes-agent`
