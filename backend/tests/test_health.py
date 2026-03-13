from unittest.mock import AsyncMock, patch

from httpx import AsyncClient


async def test_health_endpoint_healthy(client: AsyncClient) -> None:
    """Health endpoint returns healthy when database is connected."""
    with patch("app.api.health.check_database", new_callable=AsyncMock, return_value=True):
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0"
    assert data["database"] == "connected"


async def test_health_endpoint_unhealthy(client: AsyncClient) -> None:
    """Health endpoint returns unhealthy when database is disconnected."""
    with patch("app.api.health.check_database", new_callable=AsyncMock, return_value=False):
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "unhealthy"
    assert data["database"] == "disconnected"
