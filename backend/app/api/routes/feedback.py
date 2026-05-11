"""
app/api/routes/feedback.py
--------------------------
User feedback on assistant responses (thumbs up/down + optional comment).
"""

import uuid
from pydantic import BaseModel
from fastapi import APIRouter

from app.api.deps import CurrentUser, DBSession
from app.db.crud import create_feedback

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message_id: uuid.UUID
    rating: int  # 1–5; in the UI this is typically 1 (bad) or 5 (good)
    comment: str | None = None


@router.post("", status_code=201)
async def submit_feedback(
    body: FeedbackRequest, current_user: CurrentUser, db: DBSession
) -> dict:
    fb = await create_feedback(
        db,
        message_id=body.message_id,
        user_id=current_user.id,
        rating=body.rating,
        comment=body.comment,
    )
    return {"id": str(fb.id)}
