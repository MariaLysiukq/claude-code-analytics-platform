"""Health check endpoint."""
import logging

import asyncpg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(request: Request) -> JSONResponse:
    pool: asyncpg.Pool = request.app.state.pool
    try:
        async with pool.acquire() as connection:
            await connection.fetchval("SELECT 1")
    except Exception:
        logger.exception("Database health check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "disconnected"},
        )

    return JSONResponse(content={"status": "ok", "database": "connected"})
