def test_health_endpoint(client):
    """Тест ендпоінту перевірки стану системи."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
