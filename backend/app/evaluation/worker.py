"""Database-backed evaluation worker.

Run with:
    python -m app.evaluation.worker
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.db.models import EvaluationRun, utcnow
from app.db.session import AsyncSessionLocal
from app.evaluation.admin_service import write_worker_heartbeat
from app.evaluation.executor import EvaluationCancelled, execute_evaluation_run

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def claim_next_run() -> uuid.UUID | None:
    write_worker_heartbeat(state="polling")
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                select(EvaluationRun)
                .where(EvaluationRun.status == "queued")
                .order_by(EvaluationRun.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            run = result.scalar_one_or_none()
            if run is None:
                return None
            run.status = "running"
            run.started_at = utcnow()
            run.completed_at = None
            run.error_message = None
            run.metadata_ = {
                **(run.metadata_ or {}),
                "progress_message": "Evaluation worker started",
            }
            write_worker_heartbeat(state="running", run_id=run.id)
            return run.id


async def maintain_running_heartbeat(run_id: uuid.UUID, interval_s: float = 30.0) -> None:
    try:
        while True:
            write_worker_heartbeat(state="running", run_id=run_id)
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        write_worker_heartbeat(state="running", run_id=run_id)
        raise


async def run_claimed_evaluation(run_id: uuid.UUID) -> None:
    write_worker_heartbeat(state="running", run_id=run_id)
    heartbeat_task = asyncio.create_task(maintain_running_heartbeat(run_id))
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await execute_evaluation_run(session, run_id=run_id)
    except EvaluationCancelled:
        logger.info("Evaluation run %s cancelled", run_id)
    except Exception as exc:
        logger.exception("Evaluation run %s failed", run_id)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                run = await session.get(EvaluationRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.completed_at = utcnow()
                    run.error_message = str(exc)
                    run.metadata_ = {
                        **(run.metadata_ or {}),
                        "progress_message": "Evaluation failed",
                    }
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        write_worker_heartbeat(state="idle")


async def worker_loop(poll_interval_s: float = 5.0) -> None:
    logger.info("Evaluation worker started")
    write_worker_heartbeat(state="started")
    while True:
        run_id = await claim_next_run()
        if run_id is None:
            await asyncio.sleep(poll_interval_s)
            continue
        await run_claimed_evaluation(run_id)


def main() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
