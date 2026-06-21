"""
app/api/deps.py
---------------
Shared FastAPI dependencies: database session, current user, LLM provider, embedding model.
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.crud import get_user_by_id
from app.db.models import User
from app.db.session import get_db
from app.embeddings.base import EmbeddingModel
from app.embeddings.registry import get_embedding_model
from app.providers.base import LLMProvider
from app.providers.registry import get_llm_provider

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Validate JWT and return the authenticated User, or raise 401."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(credentials.credentials)
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = uuid.UUID(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def get_admin_user(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """Require admin role."""
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def get_evaluation_reviewer_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require a user allowed to complete assigned evaluation reviews."""
    if current_user.role not in {"admin", "evaluator"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Evaluator access required",
        )
    return current_user


# Type aliases for cleaner route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(get_admin_user)]
EvaluationReviewerUser = Annotated[User, Depends(get_evaluation_reviewer_user)]
DBSession = Annotated[AsyncSession, Depends(get_db)]
LLMDep = Annotated[LLMProvider, Depends(get_llm_provider)]
EmbeddingDep = Annotated[EmbeddingModel, Depends(get_embedding_model)]
