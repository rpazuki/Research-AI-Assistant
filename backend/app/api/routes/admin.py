"""
app/api/routes/admin.py
-----------------------
Admin-only endpoints for user management.
"""

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, DBSession
from app.db import crud
from app.schemas.admin import UserStatusUpdate
from app.schemas.auth import UserResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserResponse])
async def list_admin_users(_admin: AdminUser, db: DBSession) -> list[UserResponse]:
    users = await crud.list_users(db)
    return [UserResponse.model_validate(user) for user in users]


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_admin_user(
    user_id: uuid.UUID, _admin: AdminUser, db: DBSession
) -> UserResponse:
    user = await crud.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_admin_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdate,
    _admin: AdminUser,
    db: DBSession,
) -> UserResponse:
    user = await crud.get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    updated_user = await crud.update_user_active(db, user=user, is_active=body.is_active)
    return UserResponse.model_validate(updated_user)
