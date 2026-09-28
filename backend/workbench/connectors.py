"""Remote MCP transport with pinned public DNS, bounded responses and encrypted secrets."""

import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from cryptography.fernet import Fernet


def cipher():
    key = os.environ.get("LAWVER_CONNECTOR_KEY")
    if not key:
        raise HTTPException(503, "管理员尚未配置插件密钥加密服务")
    return Fernet(key.encode())


def encrypt(value):
    return cipher().encrypt(value.encode()).decode() if value else ""


def endpoint(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        raise HTTPException(422, "插件地址需要无凭据、无查询参数的 HTTPS 地址")
    if parsed.port not in (None, 443):
        raise HTTPException(422, "插件仅支持 HTTPS 443 端口")
    return value


class LimitedStream(httpx.AsyncByteStream):
    def __init__(self, source):
        self.source = source

    async def __aiter__(self):
        size = 0
        async for chunk in self.source:
            size += len(chunk)
            if size > 4 * 1024 * 1024:
                raise ValueError("MCP response too large")
            yield chunk

    async def aclose(self):
        await self.source.aclose()


class PublicTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request):
        endpoint(str(request.url))
        host = request.url.host
        records = await asyncio.to_thread(
            socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM
        )
        addresses = list(dict.fromkeys(record[4][0] for record in records))
        if not addresses or any(
            not ipaddress.ip_address(ip).is_global for ip in addresses
        ):
            raise ValueError("MCP endpoint is not public")
        # Connect to the validated IP, retaining TLS hostname verification and Host.
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=addresses[0]),
            headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": host},
        )
        response = await super().handle_async_request(pinned)
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise ValueError("MCP redirects are not permitted")
        response.stream = LimitedStream(response.stream)
        return response


async def invoke(data, name=None, arguments=None):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {}
    if data.get("encrypted_secret"):
        headers["Authorization"] = (
            "Bearer " + cipher().decrypt(data["encrypted_secret"].encode()).decode()
        )
    async with asyncio.timeout(45):
        async with httpx.AsyncClient(
            transport=PublicTransport(retries=0),
            headers=headers,
            follow_redirects=False,
            timeout=httpx.Timeout(30, connect=8),
            trust_env=False,
        ) as client:
            async with streamable_http_client(
                endpoint(data["url"]), http_client=client
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if name is None:
                        result = await session.list_tools()
                        return [tool.model_dump(mode="json") for tool in result.tools][
                            :100
                        ]
                    result = await session.call_tool(name, arguments or {})
                    return result.model_dump(mode="json")
