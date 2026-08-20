def test_get_analytics_summary_success(client, mock_db_pool):
    """Тест успішного отримання метрик використання моделей."""
    _, mock_conn = mock_db_pool

    fake_db_data = [
        {
            "model": "claude-3-5-sonnet",
            "request_count": 10,
            "total_input_tokens": 15000,
            "total_output_tokens": 5000,
            "total_cache_read_tokens": 0,
            "total_cache_creation_tokens": 0,
            "total_cost_usd": 0.045,
            "avg_cost_usd": 0.0045,
            "avg_duration_ms": 1200.0,
        }
    ]

    mock_conn.fetch.return_value = fake_db_data
    response = client.get("/api/v1/analytics/cost-by-model")

    assert response.status_code == 200
    assert response.json() == fake_db_data

def test_invalid_endpoint_returns_404(client):
    """Тест звернення до неіснуючого ендпоінту."""
    response = client.get("/api/v1/analytics/non-existent-endpoint")
    assert response.status_code == 404
