"""Helpers for evaluation worker status."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
EVALUATION_WORK_ROOT = APP_DATA_DIR / "evaluation_runs"
WORKER_HEARTBEAT_PATH = EVALUATION_WORK_ROOT / "worker_heartbeat.json"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def write_worker_heartbeat(*, state: str, run_id: uuid.UUID | None = None) -> None:
    WORKER_HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    WORKER_HEARTBEAT_PATH.write_text(
        json.dumps(
            {
                "state": state,
                "run_id": str(run_id) if run_id else None,
                "updated_at": utcnow().isoformat(),
            },
            sort_keys=True,
        )
        + "\n"
    )


def get_worker_status(stale_after_seconds: int = 120) -> dict[str, Any]:
    if not WORKER_HEARTBEAT_PATH.exists():
        return {
            "active": False,
            "state": "not_seen",
            "run_id": None,
            "updated_at": None,
            "seconds_since_heartbeat": None,
            "message": "No evaluation worker heartbeat has been seen.",
        }

    try:
        payload = json.loads(WORKER_HEARTBEAT_PATH.read_text())
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
    except Exception:
        return {
            "active": False,
            "state": "invalid",
            "run_id": None,
            "updated_at": None,
            "seconds_since_heartbeat": None,
            "message": "The evaluation worker heartbeat file is unreadable.",
        }

    age = (utcnow() - updated_at.astimezone(timezone.utc)).total_seconds()
    active = age <= stale_after_seconds
    return {
        "active": active,
        "state": payload.get("state") or "unknown",
        "run_id": payload.get("run_id"),
        "updated_at": updated_at.isoformat(),
        "seconds_since_heartbeat": int(age),
        "message": "Worker heartbeat is current." if active else "Evaluation worker heartbeat is stale.",
    }
