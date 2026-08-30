"""Tests for MediaGatewayClient, MockMediaMTXServer, and health integration."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from ibvap.api.app import create_app
from ibvap.config import Settings
from ibvap.core.media_gateway import MediaGatewayClient, MockMediaMTXServer


@pytest.mark.asyncio
async def test_mock_mediamtx_server_lifecycle() -> None:
    server = MockMediaMTXServer(host="127.0.0.1", port=0)
    api_url = await server.start()
    assert api_url.startswith("http://127.0.0.1:")
    assert server.port > 0

    client = MediaGatewayClient(api_url=api_url, timeout=2.0)
    try:
        # Check health
        health = await client.check_health()
        assert health is True

        # Initial list empty
        paths = await client.list_paths()
        assert paths == []

        # Add path
        added = await client.add_path("cam1", "rtsp://192.168.1.100:554/stream1")
        assert added is True

        # Get path
        path_info = await client.get_path("cam1")
        assert path_info is not None
        assert path_info["name"] == "cam1"
        assert path_info["source"] == "rtsp://192.168.1.100:554/stream1"

        # List paths contains cam1
        paths = await client.list_paths()
        assert len(paths) == 1
        assert paths[0]["name"] == "cam1"

        # Remove path
        removed = await client.remove_path("cam1")
        assert removed is True

        # List paths is empty again
        paths = await client.list_paths()
        assert paths == []

        # Removing nonexistent returns False
        removed_again = await client.remove_path("cam1")
        assert removed_again is False

        # Getting nonexistent returns None
        nonexistent = await client.get_path("cam_nonexistent")
        assert nonexistent is None
    finally:
        await client.close()
        await server.stop()


@pytest.mark.asyncio
async def test_media_gateway_client_context_managers() -> None:
    async with MockMediaMTXServer() as server:
        assert server.port > 0
        async with MediaGatewayClient(api_url=server.api_url) as client:
            assert await client.check_health() is True
            assert await client.add_path("test_cam", "rtsp://10.0.0.5:8554/live") is True
            paths = await client.list_paths()
            assert len(paths) == 1
            assert paths[0]["name"] == "test_cam"


@pytest.mark.asyncio
async def test_media_gateway_offline_handling() -> None:
    # Port 1 is virtually guaranteed to be closed / refused
    client = MediaGatewayClient(api_url="http://127.0.0.1:1", timeout=0.5)
    try:
        assert await client.check_health() is False
        assert await client.list_paths() == []
        assert await client.get_path("cam1") is None
        assert await client.add_path("cam1", "rtsp://fake") is False
        assert await client.remove_path("cam1") is False
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health_route_with_and_without_mediamtx() -> None:
    # 1. Without running mock server (gateway offline)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        resp = await test_client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["checks"]["media_gateway"] == "offline"

        resp_cap = await test_client.get("/api/v1/capabilities")
        assert resp_cap.status_code == 200
        cap_data = resp_cap.json()
        assert cap_data["media"]["gateway"] == "mediamtx 1.20.1 (replaceable)"

    # 2. With running mock server (gateway online)
    async with MockMediaMTXServer() as server:
        settings = Settings()
        settings.media.mediamtx_api_url = server.api_url
        app_with_mock = create_app(settings=settings)
        app_with_mock.state.settings = settings

        async with AsyncClient(transport=ASGITransport(app=app_with_mock), base_url="http://test") as test_client:
            resp = await test_client.get("/api/v1/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["checks"]["media_gateway"] == "mediamtx-1.20.1-online"

            resp_cap = await test_client.get("/api/v1/capabilities")
            assert resp_cap.status_code == 200
            cap_data = resp_cap.json()
            assert cap_data["media"]["gateway"] == "mediamtx 1.20.1 (online)"
