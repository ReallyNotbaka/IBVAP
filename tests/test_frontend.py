from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_frontend_mounted_and_serves_html(api_client: TestClient) -> None:
    client = api_client
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert '<div id="root">' in response.text
    assert "<script" in response.text


def test_frontend_spa_routing_fallbacks(api_client: TestClient) -> None:
    client = api_client
    routes = ["/monitor", "/connect/phone", "/overview", "/alerts", "/health"]
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, f"Failed on route {route}"
        assert "text/html" in response.headers.get("content-type", "")
        assert '<div id="root">' in response.text


def test_frontend_assets_served_with_correct_types(api_client: TestClient) -> None:
    dist = Path("frontend/dist/assets")
    if not dist.exists():
        return
    js_files = list(dist.glob("*.js"))
    css_files = list(dist.glob("*.css"))
    client = api_client

    if js_files:
        asset_name = js_files[0].name
        resp = client.get(f"/assets/{asset_name}")
        assert resp.status_code == 200
        assert "javascript" in resp.headers.get("content-type", "").lower()

    if css_files:
        asset_name = css_files[0].name
        resp = client.get(f"/assets/{asset_name}")
        assert resp.status_code == 200
        assert "css" in resp.headers.get("content-type", "").lower()


def test_frontend_missing_asset_returns_404(api_client: TestClient) -> None:
    client = api_client
    response = client.get("/assets/nonexistent-bundle.js")
    assert response.status_code == 404
