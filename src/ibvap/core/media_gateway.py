"""MediaMTX gateway client and in-process mock server for local dev and tests."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import unquote

import httpx
import structlog

logger = structlog.get_logger(__name__)


class MediaGatewayClient:
    """Async HTTP client for MediaMTX v3 REST API."""

    def __init__(self, api_url: str = "http://localhost:9997", timeout: float = 5.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.api_url, timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client session."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> MediaGatewayClient:
        await self._get_client()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def check_health(self) -> bool:
        """Check if MediaMTX REST API is reachable and responding."""
        try:
            client = await self._get_client()
            resp = await client.get("/v3/paths/list")
            return resp.status_code == 200
        except Exception:
            return False

    async def list_paths(self) -> list[dict[str, Any]]:
        """List active/configured paths in MediaMTX."""
        try:
            client = await self._get_client()
            resp = await client.get("/v3/paths/list")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    items = data.get("items", [])
                    if isinstance(items, list):
                        return items
            return []
        except Exception as exc:
            logger.debug("Failed to list MediaMTX paths", error=str(exc))
            return []

    async def get_path(self, name: str) -> dict[str, Any] | None:
        """Get details for a specific configured path."""
        try:
            client = await self._get_client()
            resp = await client.get(f"/v3/paths/get/{name}")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict):
                    return data
            return None
        except Exception as exc:
            logger.debug("Failed to get MediaMTX path", name=name, error=str(exc))
            return None

    async def add_path(self, name: str, source: str) -> bool:
        """Add or configure a stream path in MediaMTX."""
        try:
            client = await self._get_client()
            resp = await client.post(f"/v3/config/paths/add/{name}", json={"source": source})
            return resp.status_code in (200, 201)
        except Exception as exc:
            logger.warning("Failed to add MediaMTX path", name=name, source=source, error=str(exc))
            return False

    async def remove_path(self, name: str) -> bool:
        """Remove a stream path configuration from MediaMTX."""
        try:
            client = await self._get_client()
            resp = await client.post(f"/v3/config/paths/delete/{name}")
            return resp.status_code in (200, 201, 204)
        except Exception as exc:
            logger.warning("Failed to remove MediaMTX path", name=name, error=str(exc))
            return False


class MockMediaMTXServer:
    """Lightweight in-process HTTP mock server simulating MediaMTX v3 REST API.

    Used for unit/integration tests and offline development without external binaries.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self.paths: dict[str, dict[str, Any]] = {}
        self._server: asyncio.Server | None = None
        self.api_url: str = ""

    async def start(self) -> str:
        """Start mock server and return base API URL."""
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        sockets = self._server.sockets
        if sockets:
            self.port = sockets[0].getsockname()[1]
        self.api_url = f"http://{self.host}:{self.port}"
        return self.api_url

    async def stop(self) -> None:
        """Stop mock server and wait for close."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def __aenter__(self) -> MockMediaMTXServer:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                parts = line_str.split()
                if len(parts) < 2:
                    break
                method, url_path = parts[0].upper(), parts[1]

                content_length = 0
                close_conn = False
                while True:
                    header_line = await reader.readline()
                    if not header_line or header_line in (b"\r\n", b"\n"):
                        break
                    h_str = header_line.decode("utf-8", errors="replace").strip()
                    if ":" in h_str:
                        k, v = h_str.split(":", 1)
                        k_lower = k.strip().lower()
                        if k_lower == "content-length":
                            try:
                                content_length = int(v.strip())
                            except ValueError:
                                content_length = 0
                        elif k_lower == "connection" and v.strip().lower() == "close":
                            close_conn = True

                body_bytes = b""
                if content_length > 0:
                    body_bytes = await reader.readexactly(content_length)

                body_json: dict[str, Any] = {}
                if body_bytes:
                    try:
                        parsed = json.loads(body_bytes.decode("utf-8"))
                        if isinstance(parsed, dict):
                            body_json = parsed
                    except Exception:
                        body_json = {}

                raw_path = url_path.split("?")[0]
                status_code = 200
                resp_data: dict[str, Any] = {}

                if method == "GET" and raw_path == "/v3/paths/list":
                    items = [{"name": k, **v} for k, v in self.paths.items()]
                    resp_data = {
                        "itemCount": len(items),
                        "pageCount": 1,
                        "items": items,
                    }
                elif method == "POST" and raw_path.startswith("/v3/config/paths/add/"):
                    name = unquote(raw_path[len("/v3/config/paths/add/") :])
                    self.paths[name] = body_json
                    resp_data = {"status": "ok", "name": name, "item": body_json}
                elif method in ("POST", "DELETE") and raw_path.startswith("/v3/config/paths/delete/"):
                    name = unquote(raw_path[len("/v3/config/paths/delete/") :])
                    existed = self.paths.pop(name, None) is not None
                    if existed:
                        resp_data = {"status": "ok", "name": name}
                    else:
                        status_code = 404
                        resp_data = {"error": f"path '{name}' not found"}
                elif method == "GET" and raw_path.startswith("/v3/paths/get/"):
                    name = unquote(raw_path[len("/v3/paths/get/") :])
                    if name in self.paths:
                        resp_data = {"name": name, **self.paths[name]}
                    else:
                        status_code = 404
                        resp_data = {"error": f"path '{name}' not found"}
                else:
                    status_code = 404
                    resp_data = {"error": f"endpoint '{raw_path}' not found"}

                resp_bytes = json.dumps(resp_data).encode()
                status_text = "OK" if status_code == 200 else "Not Found"
                conn_header = "close" if close_conn else "keep-alive"
                headers = (
                    f"HTTP/1.1 {status_code} {status_text}\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(resp_bytes)}\r\n"
                    f"Connection: {conn_header}\r\n\r\n"
                ).encode()
                writer.write(headers + resp_bytes)
                await writer.drain()

                if close_conn:
                    break
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
