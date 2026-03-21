"""
/api/jobs — Cron job management for Hermes Workspace.

Reads/writes the same job store as the gateway cron scheduler
(~/.hermes/cron/jobs.json) so the Workspace UI can list, create,
pause, resume, trigger, update, and delete cron jobs.
"""

import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from cron.jobs import (
    create_job,
    get_job,
    list_jobs,
    load_jobs,
    pause_job,
    remove_job,
    resume_job,
    trigger_job,
    update_job,
    OUTPUT_DIR,
)


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class JobCreateRequest(BaseModel):
    prompt: str
    schedule: str
    name: str | None = None
    repeat: int | None = None
    deliver: str | None = None
    skills: list[str] | None = None
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None


class JobPatchRequest(BaseModel):
    name: str | None = None
    prompt: str | None = None
    schedule: str | None = None
    enabled: bool | None = None
    deliver: str | None = None
    skills: list[str] | None = None
    model: str | None = None
    provider: str | None = None
    base_url: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _job_or_404(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


def _get_job_outputs(job_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Read recent output files for a job from the output directory."""
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.is_dir():
        return []

    files = sorted(job_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    outputs = []
    for f in files[:limit]:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            stat = f.stat()
            outputs.append({
                "filename": f.name,
                "timestamp": f.stem,  # e.g. "2026-03-21_14-30-00"
                "content": content,
                "size": stat.st_size,
            })
        except OSError:
            continue
    return outputs


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("")
async def list_all_jobs(include_disabled: bool = Query(False)) -> dict:
    """List all jobs. Pass ?include_disabled=true to include paused/disabled jobs."""
    jobs = list_jobs(include_disabled=include_disabled)
    return {"jobs": jobs}


@router.post("", status_code=201)
async def create_new_job(payload: JobCreateRequest) -> dict:
    """Create a new cron job."""
    try:
        job = create_job(
            prompt=payload.prompt,
            schedule=payload.schedule,
            name=payload.name,
            repeat=payload.repeat,
            deliver=payload.deliver,
            skills=payload.skills,
            model=payload.model,
            provider=payload.provider,
            base_url=payload.base_url,
        )
        return {"job": job}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{job_id}")
async def get_single_job(job_id: str) -> dict:
    """Get a single job by ID."""
    job = _job_or_404(job_id)
    return {"job": job}


@router.patch("/{job_id}")
async def patch_job(job_id: str, payload: JobPatchRequest) -> dict:
    """Update a job's fields."""
    _job_or_404(job_id)  # ensure exists

    updates: dict[str, Any] = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.prompt is not None:
        updates["prompt"] = payload.prompt
    if payload.schedule is not None:
        from cron.jobs import parse_schedule
        try:
            parsed = parse_schedule(payload.schedule)
            updates["schedule"] = parsed
            updates["schedule_display"] = parsed.get("display", payload.schedule)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    if payload.enabled is not None:
        updates["enabled"] = payload.enabled
    if payload.deliver is not None:
        updates["deliver"] = payload.deliver
    if payload.skills is not None:
        updates["skills"] = payload.skills
    if payload.model is not None:
        updates["model"] = payload.model
    if payload.provider is not None:
        updates["provider"] = payload.provider
    if payload.base_url is not None:
        updates["base_url"] = payload.base_url

    job = update_job(job_id, updates)
    if not job:
        raise HTTPException(status_code=500, detail="Failed to update job")
    return {"job": job}


@router.delete("/{job_id}")
async def delete_single_job(job_id: str) -> dict:
    """Delete a job."""
    if not remove_job(job_id):
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"ok": True, "job_id": job_id}


@router.post("/{job_id}/pause")
async def pause_single_job(job_id: str) -> dict:
    """Pause a job."""
    job = pause_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"job": job}


@router.post("/{job_id}/resume")
async def resume_single_job(job_id: str) -> dict:
    """Resume a paused job."""
    job = resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"job": job}


@router.post("/{job_id}/run")
async def trigger_single_job(job_id: str) -> dict:
    """Trigger immediate execution of a job on the next scheduler tick."""
    job = trigger_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"job": job}


@router.get("/{job_id}/output")
async def get_job_output(job_id: str, limit: int = Query(10, ge=1, le=100)) -> dict:
    """Get recent output files for a job."""
    _job_or_404(job_id)
    outputs = _get_job_outputs(job_id, limit=limit)
    return {"outputs": outputs}
