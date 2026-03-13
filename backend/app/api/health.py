from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_session
from app.schemas.health import HealthResponse
from app.services.health import check_database

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    db_ok = await check_database(session)
    return HealthResponse(
        status="healthy" if db_ok else "unhealthy",
        version=settings.app_version,
        database="connected" if db_ok else "disconnected",
    )
