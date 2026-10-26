"""有界公网读取：禁止私网/凭据/非标准端口，固定DNS解析结果并逐跳检查重定向。"""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx


async def public_address(url):
    if (
        not isinstance(url, str)
        or len(url) > 4096
        or any(c.isspace() or ord(c) < 32 for c in url)
        or "\\" in url
    ):
        raise ValueError("网址格式不合法")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 80, 443}
    ):
        raise ValueError("仅允许不含认证信息的标准HTTP(S)公网地址")
    answers = await asyncio.to_thread(
        socket.getaddrinfo,
        parsed.hostname,
        parsed.port or (443 if parsed.scheme == "https" else 80),
        type=socket.SOCK_STREAM,
    )
    addresses = list(dict.fromkeys(row[4][0] for row in answers))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("禁止访问本机、私网、保留地址及云实例元数据")
    return parsed, sorted(addresses, key=lambda value: ":" in value)


async def fetch_public(url, *, limit=2_000_000, accept="text/html", allowed=None):
    """HTTPS仍校验原域名证书；连接固定IP，阻止检查后DNS重绑定。"""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(18, connect=8), trust_env=False, follow_redirects=False
    ) as client:
        for _ in range(5):
            parsed, addresses = await public_address(url)
            if allowed is not None and not allowed(parsed.hostname):
                raise ValueError("该网页域名未在管理员批准的范围内")
            last = None
            for address in addresses[:3]:
                try:
                    target = httpx.URL(url).copy_with(host=address)
                    request = client.build_request(
                        "GET",
                        target,
                        headers={
                            "Host": parsed.hostname,
                            "Accept": accept,
                            "User-Agent": "Mozilla/5.0 (compatible; ShiGuangResearch/1.0)",
                        },
                    )
                    request.extensions["sni_hostname"] = parsed.hostname
                    response = await client.send(request, stream=True)
                    try:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("location")
                            if not location:
                                raise ValueError("重定向缺少目标")
                            url = urljoin(url, location)
                            break
                        response.raise_for_status()
                        parts = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > limit:
                                raise ValueError("网页或图片超过大小限制")
                            parts.append(chunk)
                        return url, response.headers, b"".join(parts)
                    finally:
                        await response.aclose()
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    last = exc
            else:
                raise last or ValueError("公网连接失败")
        raise ValueError("重定向次数过多")
