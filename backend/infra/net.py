"""
模块描述：出站请求的代理口径——本机与内网目标一律直连，公网目标照常走环境/系统代理。

为什么需要：开着系统代理（Clash 一类工具会写 Windows 注册表 / macOS 网络设置）时，
httpx（openai SDK 与分流核心都用它）会读到这个系统代理，却不读系统的「绕过列表」，
于是指向 127.0.0.1 的本地模型、局域网里的推理服务也被转给代理，常见结果是代理回 502；
而用 requests 写的「测试连接」会按绕过列表直连，于是出现「测试连接通过、对话却 502」。
requests/urllib 虽然认 Windows 的绕过列表，但只设了 HTTP(S)_PROXY 环境变量、没设
NO_PROXY 时同样会把本机请求送去代理。

这里只做一件事：判断目标是不是本机/内网。是就让调用方关掉代理；不是就什么都不改，
公网接口（境外模型 API 等）仍按原来的代理设置访问。
"""

from __future__ import annotations

import ipaddress
import ssl
import urllib.request
from typing import Optional
from urllib.parse import urlsplit


def is_local_host(host: Optional[str]) -> bool:
    """本机、内网或单标签主机名（与系统代理 <local> 规则同口径）。"""
    if not host:
        return False
    name = host.strip().strip("[]").rstrip(".").lower()
    if not name:
        return False
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        # 不带点的主机名：容器服务名（ollama、searxng）或局域网机器名，不可能经公网代理到达。
        return "." not in name
    return address.is_loopback or address.is_private or address.is_link_local


def is_local_url(url: Optional[str]) -> bool:
    try:
        return is_local_host(urlsplit(str(url or "")).hostname)
    except ValueError:
        return False


def requests_proxies(url: Optional[str]) -> Optional[dict]:
    """requests 的 proxies 参数。

    本机/内网目标显式置空：requests 合并环境代理时用 setdefault，已有的 None 不会被覆盖，
    最后统一剔除，于是环境变量与系统代理都不生效。公网目标返回 None，行为与不传完全一致。
    """
    if is_local_url(url):
        return {"http": None, "https": None, "all": None}
    return None


def urlopen(
    request: urllib.request.Request,
    *,
    timeout: float,
    context: Optional[ssl.SSLContext] = None,
):
    """urllib.request.urlopen 的同口径替代：本机/内网目标不经任何代理。"""
    if not is_local_url(request.full_url):
        return urllib.request.urlopen(request, timeout=timeout, context=context)
    handlers: list[urllib.request.BaseHandler] = [urllib.request.ProxyHandler({})]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)
