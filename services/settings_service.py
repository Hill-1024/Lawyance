"""
模块描述：运行时设置读写服务，以 DATA_DIR/settings.json 持久化 provider 配置。
"""
import json
import os
import threading
from pathlib import Path

DATA_DIR = os.environ.get("LAWVER_DATA_DIR") or os.path.join(os.getcwd(), "data")
os.makedirs(DATA_DIR, exist_ok=True)
SETTINGS_FILE = Path(DATA_DIR) / "settings.json"
_SETTINGS_LOCK = threading.RLock()

PROVIDER_KEYS = {
    "llm": {
        "label": "大模型 (LLM)",
        "env": {"base_url": "BASE_URL", "model": "LLM_MODEL", "api_key": "API_KEY"},
        "defaults": {"base_url": "https://api.openai.com/v1", "model": ""},
    },
    "deli": {
        "label": "得理法搜",
        "env": {"endpoint": "DELI_ENDPOINT"},
        "defaults": {"endpoint": ""},
    },
    "searxng": {
        "label": "网页检索 (SearXNG)",
        "env": {"base_url": "SEARXNG_BASE_URL", "engines": "SEARXNG_ENGINES"},
        "defaults": {"base_url": "", "language": "all", "safe_search": "0", "engines": "", "categories": ""},
    },
    "qcc": {
        "label": "企业信息 (企查查)",
        "env": {"endpoint": "QCC_ENDPOINT"},
        "defaults": {"endpoint": ""},
    },
    "embedding": {
        "label": "嵌入模型 (Embedding)",
        "env": {"base_url": "EMBEDDING_BASE_URL", "model": "EMBEDDING_MODEL"},
        "defaults": {"base_url": "", "model": ""},
    },
}

DEFAULT_SETTINGS = {
    "version": 1,
    "providers": {
        key: {
            "enabled": any(os.environ.get(e) for e in info["env"].values()),
            **info["defaults"],
        }
        for key, info in PROVIDER_KEYS.items()
    },
}


def _read_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_SETTINGS


def get_settings() -> dict:
    """返回当前持久化设置，未持久化的 provider 用环境变量兜底。"""
    with _SETTINGS_LOCK:
        saved = _read_settings()
    merged = dict(saved)
    merged.setdefault("providers", {})
    for key, info in PROVIDER_KEYS.items():
        provider = merged["providers"].setdefault(key, {"enabled": False})
        for field, env_var in info["env"].items():
            env_value = os.environ.get(env_var)
            if env_value:
                provider[field] = env_value
        provider.setdefault("enabled", False)
    return merged


def update_settings(payload: dict) -> dict:
    """管理员保存 provider 配置。只接受 providers 子项。"""
    with _SETTINGS_LOCK:
        current = _read_settings()
    new_providers = payload.get("providers", {})
    if not isinstance(new_providers, dict):
        raise ValueError("providers 必须是对象")
    current_providers = current.setdefault("providers", {})
    for key, value in new_providers.items():
        if key not in PROVIDER_KEYS:
            continue
        merged = dict(current_providers.get(key, {}))
        merged.update(value)
        current_providers[key] = merged
    with _SETTINGS_LOCK:
        os.makedirs(SETTINGS_FILE.parent, exist_ok=True)
        tmp = str(SETTINGS_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, SETTINGS_FILE)
    return get_settings()


def get_provider_statuses() -> list[dict]:
    """返回各 provider 的启用状态与配置摘要。"""
    settings = get_settings()
    result = []
    for key, info in PROVIDER_KEYS.items():
        provider = settings.get("providers", {}).get(key, {})
        configured = any(
            provider.get(field) or os.environ.get(env_var)
            for field, env_var in info["env"].items()
        )
        result.append({
            "provider": key,
            "label": info["label"],
            "enabled": bool(provider.get("enabled", False)),
            "configured": configured,
            "ok": configured and bool(provider.get("enabled", False)),
            "message": "已配置" if configured else "未配置环境变量",
        })
    return result


def test_provider_connection(key: str) -> dict:
    """对指定 provider 做连通性探测。目前仅验证配置是否存在。"""
    if key not in PROVIDER_KEYS:
        return {"provider": key, "ok": False, "message": f"未知的 provider: {key}"}
    settings = get_settings()
    provider = settings.get("providers", {}).get(key, {})
    info = PROVIDER_KEYS[key]
    missing = [
        field for field, env_var in info["env"].items()
        if not provider.get(field) and not os.environ.get(env_var)
    ]
    if missing:
        return {
            "provider": key,
            "ok": False,
            "message": f"缺少配置: {', '.join(missing)}",
        }
    return {
        "provider": key,
        "ok": True,
        "message": f"{info['label']} 已配置",
    }
