"""Async PostgreSQL connection pool (asyncpg)."""
import logging
from typing import AsyncIterator

import asyncpg
from fastapi import Request

from api.config import Settings

logger = logging.getLogger(__name__)


async def create_pool(settings: Settings) -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
        host=settings.postgres_host,
        port=settings.postgres_port,
        min_size=1,
        max_size=10,
    )
    logger.info("Postgres connection pool created")
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    await pool.close()
    logger.info("Postgres connection pool closed")


async def get_connection(request: Request) -> AsyncIterator[asyncpg.Connection]:
    """FastAPI dependency yielding a connection from the app-wide pool."""
    pool: asyncpg.Pool = request.app.state.pool
    async with pool.acquire() as connection:
        yield connection
