"""Async PostgreSQL connection pool (asyncpg)."""

import logging

import asyncpg

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
