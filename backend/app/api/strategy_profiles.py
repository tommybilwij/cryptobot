"""HTTP API for managing strategy profiles."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/api/v1/strategy-profiles", tags=["strategy-profiles"])

DbSession = Annotated[AsyncSession, Depends(get_db)]


class ProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    config: dict[str, Any]


class CloneRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=120)


class ProfileResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    config: dict[str, Any]
    version: int
    is_active: bool


@router.post("", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(req: ProfileCreateRequest, db: DbSession) -> ProfileResponse:
    service = ProfileService(db)
    try:
        created = await service.create(
            name=req.name, description=req.description, config=req.config
        )
    except ValueError as e:  # pydantic ValidationError subclasses ValueError
        raise HTTPException(status_code=422, detail=str(e)) from e
    await db.commit()
    return ProfileResponse.model_validate(created, from_attributes=True)


@router.get("", response_model=list[ProfileResponse])
async def list_profiles(db: DbSession) -> list[ProfileResponse]:
    service = ProfileService(db)
    rows = await service.list_all()
    return [ProfileResponse.model_validate(r, from_attributes=True) for r in rows]


@router.get("/active", response_model=ProfileResponse)
async def get_active(db: DbSession) -> ProfileResponse:
    service = ProfileService(db)
    row = await service.get_active()
    if row is None:
        raise HTTPException(status_code=404, detail="no active profile")
    return ProfileResponse.model_validate(row, from_attributes=True)


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(profile_id: uuid.UUID, db: DbSession) -> ProfileResponse:
    service = ProfileService(db)
    row = await service.get(profile_id)
    if row is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return ProfileResponse.model_validate(row, from_attributes=True)


@router.post("/{profile_id}/apply", response_model=ProfileResponse)
async def apply(profile_id: uuid.UUID, db: DbSession) -> ProfileResponse:
    service = ProfileService(db)
    try:
        row = await service.apply(profile_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await db.commit()
    return ProfileResponse.model_validate(row, from_attributes=True)


@router.post(
    "/{profile_id}/clone",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone(
    profile_id: uuid.UUID,
    req: CloneRequest,
    db: DbSession,
) -> ProfileResponse:
    service = ProfileService(db)
    try:
        row = await service.clone(profile_id, new_name=req.new_name)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    await db.commit()
    return ProfileResponse.model_validate(row, from_attributes=True)
