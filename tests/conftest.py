from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def mock_db_pool():
    mock_conn = AsyncMock()
    pool = MagicMock()

    # Налаштування для: async with pool.acquire() as connection:
    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = acquire_cm

    # Налаштування для: await pool.close()
    pool.close = AsyncMock()

    return pool, mock_conn


@pytest.fixture
def client(mock_db_pool):
    pool, _ = mock_db_pool
    with patch("api.main.create_pool", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = pool
        with TestClient(app) as test_client:
            test_client.app.state.pool = pool
            yield test_client
