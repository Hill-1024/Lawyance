"""
模块描述：全局域名与端口配置，统一取自 package.json 的 appConfig，客户端与服务端共用同一份。
"""

import json
from pathlib import Path

# 兜底默认值：仅当 package.json 缺失或损坏时生效；日常修改域名/端口请直接改 package.json。
_FALLBACK_DOMAIN = "cn.lawver.dev"
_FALLBACK_PORT = 8080


def _load_app_config() -> dict:
    try:
        raw = (Path(__file__).resolve().parent / "package.json").read_text(encoding="utf-8")
        config = json.loads(raw).get("appConfig")
    except (OSError, ValueError):
        return {}
    return config if isinstance(config, dict) else {}


APP_CONFIG = _load_app_config()

DOMAIN = str(APP_CONFIG.get("domain") or _FALLBACK_DOMAIN)
PORT = int(APP_CONFIG.get("port") or _FALLBACK_PORT)
ORIGIN = f"https://{DOMAIN}"
