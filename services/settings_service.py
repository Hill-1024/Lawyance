"""
模块描述：运行时设置读写服务，以 DATA_DIR/settings.json 持久化 provider 配置。
"""
import json
import os
import threading
import time
from pathlib import Path

import requests

DATA_DIR = os.environ.get("LAWVER_DATA_DIR") or os.path.join(os.getcwd(), "data")
SETTINGS_FILE = Path(DATA_DIR) / "settings.json"
SECRETS_FILE = Path(DATA_DIR) / "secrets.json"
_SETTINGS_LOCK = threading.RLock()
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def _ensure_private_data_dir() -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, mode=PRIVATE_DIR_MODE, exist_ok=True)
    os.chmod(SETTINGS_FILE.parent, PRIVATE_DIR_MODE)


def _harden_private_file(path: Path) -> None:
    try:
        os.chmod(path, PRIVATE_FILE_MODE)
    except FileNotFoundError:
        return


def _atomic_write_private_json(path: Path, payload: dict) -> None:
    _ensure_private_data_dir()
    tmp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp"
    )
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    try:
        os.fchmod(fd, PRIVATE_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        _harden_private_file(path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


_ensure_private_data_dir()
_harden_private_file(SETTINGS_FILE)
_harden_private_file(SECRETS_FILE)

PROVIDER_SPECS = {
    "llm": {
        "label": "大模型 (LLM)",
        "config_env": {
            "base_url": ("BASE_URL",),
            "model": ("LLM_MODEL",),
        },
        "secret_env": {
            "api_key": ("API_KEY",),
        },
        "defaults": {"base_url": "https://api.openai.com/v1", "model": ""},
        "required": ("base_url", "model", "api_key"),
    },
    "deli": {
        "label": "得理法搜",
        "config_env": {
            "endpoint": ("DELI_ENDPOINT",),
        },
        "secret_env": {
            "appid": ("DELI_APPID",),
            "secret": ("DELI_SECRET",),
        },
        "defaults": {"endpoint": "https://openapi.delilegal.com/api/qa/v3/search/queryListCase"},
        "required": ("appid", "secret"),
    },
    "searxng": {
        "label": "网页检索 (SearXNG)",
        "config_env": {
            "base_url": ("SEARXNG_BASE_URL",),
            "language": ("SEARXNG_LANGUAGE",),
            "safe_search": ("SEARXNG_SAFE_SEARCH",),
            "engines": ("SEARXNG_ENGINES",),
            "categories": ("SEARXNG_CATEGORIES",),
        },
        "secret_env": {
            "cf_client_id": ("SEARXNG_CF_ACCESS_CLIENT_ID", "CF_ACCESS_CLIENT_ID"),
            "cf_client_secret": ("SEARXNG_CF_ACCESS_CLIENT_SECRET", "CF_ACCESS_CLIENT_SECRET"),
        },
        "defaults": {
            "base_url": "https://serp.mutsumi.moe/",
            "language": "all",
            "safe_search": "0",
            "engines": "",
            "categories": "",
        },
        "required": ("cf_client_id", "cf_client_secret"),
    },
    "qcc": {
        "label": "企业信息 (企查查)",
        "config_env": {
            "endpoint": ("QCC_ENDPOINT",),
        },
        "secret_env": {
            "access_token": ("QCC_ACCESS_TOKEN",),
        },
        "defaults": {"endpoint": "https://agent.qcc.com/mcp/company/stream"},
        "required": ("access_token",),
    },
    "embedding": {
        "label": "嵌入模型 (Embedding)",
        "config_env": {
            "base_url": ("EMBEDDING_BASE_URL", "MEMORY_EMBEDDING_BASE_URL"),
            "model": ("EMBEDDING_MODEL", "MEMORY_EMBEDDING_MODEL"),
        },
        "secret_env": {
            "api_key": ("EMBEDDING_API_KEY", "MEMORY_EMBEDDING_API_KEY", "SILICONFLOW_API_KEY"),
        },
        "defaults": {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "Qwen/Qwen3-Embedding-8B",
        },
        "required": ("api_key",),
    },
}


def _env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _read_settings() -> dict:
    if SETTINGS_FILE.exists():
        _harden_private_file(SETTINGS_FILE)
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _normalized_saved_settings() -> dict:
    saved = _read_settings()
    if not isinstance(saved, dict):
        saved = {}
    providers = saved.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    return {
        "version": saved.get("version", 1),
        "providers": providers,
    }


def _provider_saved_settings(provider_key: str) -> dict:
    saved = _normalized_saved_settings()
    provider = saved["providers"].get(provider_key)
    return provider if isinstance(provider, dict) else {}


def _merge_saved_and_env_fields(
    provider_key: str,
    *,
    include_secrets: bool,
) -> dict:
    spec = PROVIDER_SPECS[provider_key]
    saved_provider = _provider_saved_settings(provider_key)

    merged = {
        "enabled": bool(saved_provider.get("enabled", False)),
    }
    for field in spec["config_env"]:
        if field in saved_provider and saved_provider[field] is not None:
            merged[field] = saved_provider[field]

    for field, env_names in spec["config_env"].items():
        if merged.get(field) in (None, ""):
            env_value = _env_value(*env_names)
            if env_value:
                merged[field] = env_value

    for field, default_value in spec["defaults"].items():
        if merged.get(field) in (None, ""):
            merged[field] = default_value

    if include_secrets:
        saved_secrets = _read_secrets().get(provider_key, {})
        if isinstance(saved_secrets, dict):
            for field in spec["secret_env"]:
                if field in saved_secrets and saved_secrets[field] is not None:
                    merged[field] = saved_secrets[field]
        for field, env_names in spec["secret_env"].items():
            if merged.get(field) in (None, ""):
                env_value = _env_value(*env_names)
                if env_value:
                    merged[field] = env_value

    if "enabled" not in saved_provider:
        merged["enabled"] = any(
            merged.get(field)
            for field in (*spec["config_env"], *spec["secret_env"])
        )

    return merged


def get_settings() -> dict:
    """返回当前设置快照，仅暴露非敏感字段。"""
    with _SETTINGS_LOCK:
        saved = _normalized_saved_settings()
        return {
            "version": saved.get("version", 1),
            "providers": {
                key: _merge_saved_and_env_fields(key, include_secrets=False)
                for key in PROVIDER_SPECS
            },
        }


def get_provider_runtime_config(provider_key: str) -> dict:
    """返回供运行时使用的 provider 配置，包含敏感字段。"""
    if provider_key not in PROVIDER_SPECS:
        return {}
    with _SETTINGS_LOCK:
        return _merge_saved_and_env_fields(provider_key, include_secrets=True)


def update_settings(payload: dict) -> dict:
    """管理员保存 provider 配置。只接受 providers 子项。"""
    with _SETTINGS_LOCK:
        current = _normalized_saved_settings()
        new_providers = payload.get("providers", {})
        if not isinstance(new_providers, dict):
            raise ValueError("providers 必须是对象")
        current_providers = current.setdefault("providers", {})
        for key, value in new_providers.items():
            if key not in PROVIDER_SPECS:
                continue
            if not isinstance(value, dict):
                raise ValueError(f"{key} 配置必须是对象")
            allowed_fields = {"enabled", *PROVIDER_SPECS[key]["config_env"].keys()}
            merged = dict(current_providers.get(key, {}))
            for field in allowed_fields:
                if field in value:
                    merged[field] = value[field]
            current_providers[key] = merged
        _atomic_write_private_json(SETTINGS_FILE, current)
        return get_settings()


def get_provider_statuses() -> list[dict]:
    """返回各 provider 的启用状态与配置摘要。"""
    result = []
    for key, info in PROVIDER_SPECS.items():
        provider = get_provider_runtime_config(key)
        missing = _missing_required_fields(key, provider)
        configured = not missing
        enabled = bool(provider.get("enabled", False))
        if missing:
            message = f"缺少配置: {', '.join(missing)}"
        elif enabled:
            message = "已就绪"
        else:
            message = "已配置，未启用"
        result.append({
            "provider": key,
            "label": info["label"],
            "enabled": enabled,
            "configured": configured,
            "ok": configured,
            "message": message,
        })
    return result


def test_provider_connection(key: str) -> dict:
    """对指定 provider 做配置完整性探测。"""
    if key not in PROVIDER_SPECS:
        return {"provider": key, "ok": False, "message": f"未知的 provider: {key}"}
    provider = get_provider_runtime_config(key)
    info = PROVIDER_SPECS[key]
    missing = _missing_required_fields(key, provider)
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


def _read_secrets() -> dict:
    if SECRETS_FILE.exists():
        _harden_private_file(SECRETS_FILE)
        try:
            with open(SECRETS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def set_secret(provider: str, key: str, value: str):
    _validate_secret_target(provider, key)
    with _SETTINGS_LOCK:
        secrets = _read_secrets()
        secrets.setdefault(provider, {})[key] = value
        _atomic_write_private_json(SECRETS_FILE, secrets)


def clear_secret(provider: str, key: str | None = None):
    if provider not in PROVIDER_SPECS:
        raise ValueError("未知的 provider")
    if key is not None:
        _validate_secret_target(provider, key)
    with _SETTINGS_LOCK:
        secrets = _read_secrets()
        if key:
            secrets.get(provider, {}).pop(key, None)
            if not secrets.get(provider):
                secrets.pop(provider, None)
        else:
            secrets.pop(provider, None)
        _atomic_write_private_json(SECRETS_FILE, secrets)


def get_secret(provider: str, key: str) -> str | None:
    secrets = _read_secrets()
    return secrets.get(provider, {}).get(key)


def _validate_secret_target(provider: str, key: str) -> None:
    spec = PROVIDER_SPECS.get(provider)
    if not spec:
        raise ValueError("未知的 provider")
    if key not in spec["secret_env"]:
        raise ValueError("该 provider 不支持此密钥字段")


def fetch_llm_models() -> list[dict]:
    llm = get_provider_runtime_config("llm")
    missing = _missing_required_fields("llm", llm)
    if "base_url" in missing or "api_key" in missing:
        return []
    base_url = str(llm.get("base_url") or "").rstrip("/")
    api_key = str(llm.get("api_key") or "")
    try:
        response = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            models = data if isinstance(data, list) else data.get("data", [])
            return [{"id": m.get("id", ""), "owned_by": m.get("owned_by", "")} for m in models]
    except Exception:
        pass
    return []


def _missing_required_fields(provider_key: str, provider: dict) -> list[str]:
    spec = PROVIDER_SPECS[provider_key]
    missing = []
    for field in spec["required"]:
        value = provider.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    return missing
