"""
模块描述：运行时设置读写服务，以 DATA_DIR/settings.json 持久化 provider 配置。
"""
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

import requests

DATA_DIR = os.environ.get("LAWVER_DATA_DIR") or os.path.join(os.getcwd(), "data")
SETTINGS_FILE = Path(DATA_DIR) / "settings.json"
SECRETS_FILE = Path(DATA_DIR) / "secrets.json"
_SETTINGS_LOCK = threading.RLock()
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600

# LLM 配置档案（可保存多套模型端点，一键切换，无需重复填写）。
MAX_LLM_PROFILES = 24
MAX_PROFILE_NAME_CHARS = 64
MAX_PROFILE_ID_CHARS = 64
_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ALLOWED_URL_SCHEMES = ("http://", "https://")


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
    profiles = saved.get("llm_profiles")
    if not isinstance(profiles, list):
        profiles = []
    normalized_profiles = []
    seen_ids = set()
    for item in profiles:
        if not isinstance(item, dict):
            continue
        profile_id = item.get("id")
        if not _is_valid_profile_id(profile_id) or profile_id in seen_ids:
            continue
        seen_ids.add(profile_id)
        normalized_profiles.append({
            "id": profile_id,
            "name": _clean_profile_name(item.get("name")) or profile_id,
            "base_url": str(item.get("base_url") or "").strip(),
            "model": str(item.get("model") or "").strip(),
            "enabled": bool(item.get("enabled", True)),
        })
    active = saved.get("active_llm_profile")
    if not isinstance(active, str) or active not in seen_ids:
        active = ""
    return {
        "version": saved.get("version", 1),
        "providers": providers,
        "llm_profiles": normalized_profiles,
        "active_llm_profile": active,
    }


def _is_valid_profile_id(value) -> bool:
    return isinstance(value, str) and bool(_PROFILE_ID_RE.fullmatch(value))


def _clean_profile_name(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_PROFILE_NAME_CHARS]


def _validate_profile_endpoint(base_url: str) -> str:
    candidate = str(base_url or "").strip()
    if not candidate:
        raise ValueError("Base URL 不能为空")
    if len(candidate) > 4_096:
        raise ValueError("Base URL 过长")
    if not candidate.lower().startswith(_ALLOWED_URL_SCHEMES):
        raise ValueError("Base URL 必须以 http:// 或 https:// 开头")
    return candidate


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
        _mirror_llm_provider_into_active_profile(current)
        _atomic_write_private_json(SETTINGS_FILE, current)
        return get_settings()


def _mirror_llm_provider_into_active_profile(state: dict) -> None:
    """管理员直接编辑 providers.llm 时同步回活动档案，避免两处配置分叉。"""
    active = state.get("active_llm_profile")
    profiles = state.get("llm_profiles") or []
    if not active or not isinstance(profiles, list):
        return
    provider = (state.get("providers") or {}).get("llm")
    if not isinstance(provider, dict):
        return
    for profile in profiles:
        if profile.get("id") != active:
            continue
        if "base_url" in provider:
            profile["base_url"] = str(provider.get("base_url") or "").strip()
        if "model" in provider:
            profile["model"] = str(provider.get("model") or "").strip()
        return


# ─── LLM 配置档案 ───────────────────────────────────────────────────────────


def _profile_secret_map() -> dict:
    secrets = _read_secrets()
    stored = secrets.get("llm_profiles")
    return stored if isinstance(stored, dict) else {}


def _profile_api_key(profile_id: str) -> str:
    entry = _profile_secret_map().get(profile_id)
    if isinstance(entry, dict):
        return str(entry.get("api_key") or "")
    return ""


def _write_profile_api_key(profile_id: str, api_key: str) -> None:
    with _SETTINGS_LOCK:
        secrets = _read_secrets()
        profiles = secrets.setdefault("llm_profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
            secrets["llm_profiles"] = profiles
        if api_key:
            profiles[profile_id] = {"api_key": api_key}
        else:
            profiles.pop(profile_id, None)
        _atomic_write_private_json(SECRETS_FILE, secrets)


def _effective_llm_config() -> dict:
    """活动档案优先，其次 providers.llm（含 env 回退）与 llm.api_key。

    关键约束：base_url 与 model 必须来自同一个来源。档案缺少任一项时整体回退到
    环境变量，否则会把档案的端点与环境变量的模型拼成错配组合（例如把 deepseek
    的模型名发到 api.openai.com），模型侧只会报"不接受输入"。
    """
    with _SETTINGS_LOCK:
        state = _normalized_saved_settings()
        active = state.get("active_llm_profile") or ""
        provider = _merge_saved_and_env_fields("llm", include_secrets=True)
        env_config = {
            "profile_id": "",
            "name": "环境变量默认",
            "base_url": str(provider.get("base_url") or ""),
            "model": str(provider.get("model") or ""),
            "api_key": str(provider.get("api_key") or ""),
            "enabled": bool(provider.get("enabled", False)),
        }
        profile = next((p for p in state["llm_profiles"] if p["id"] == active), None)
        if profile is None or not is_profile_complete(profile):
            return env_config
        return {
            "profile_id": active,
            "name": profile["name"],
            "base_url": profile["base_url"],
            "model": profile["model"],
            # 档案没自带密钥时才借用环境变量，端点与模型仍取自档案，保持同源。
            "api_key": _profile_api_key(active) or env_config["api_key"],
            "enabled": bool(profile.get("enabled", True)),
        }


def is_profile_complete(profile: dict) -> bool:
    """档案必须自带端点与模型才算可用；缺任一项都不能参与运行时解析。"""
    return bool(str(profile.get("base_url") or "").strip()) and bool(str(profile.get("model") or "").strip())


def resolve_active_llm_config() -> dict:
    """运行时（function_calling / OCP）读取实际生效的模型配置。"""
    try:
        return _effective_llm_config()
    except Exception:
        return {}


def list_llm_profiles() -> dict:
    """返回全部档案（不含 api_key）与当前活动档案 id。"""
    with _SETTINGS_LOCK:
        state = _normalized_saved_settings()
        if not state["llm_profiles"]:
            _seed_llm_profile(state)
        active = state["active_llm_profile"] or ""
        effective = _effective_llm_config()
        # 只有真正被运行时采用的档案才算"使用中"；信息不完整的会被跳过。
        effective_id = effective.get("profile_id", "")
        profiles = []
        for profile in state["llm_profiles"]:
            complete = is_profile_complete(profile)
            profiles.append({
                "id": profile["id"],
                "name": profile["name"],
                "base_url": profile["base_url"],
                "model": profile["model"],
                "enabled": bool(profile.get("enabled", True)),
                "has_api_key": bool(_profile_api_key(profile["id"])),
                "incomplete": not complete,
                "active": bool(complete) and profile["id"] == effective_id,
            })
        return {
            "profiles": profiles,
            "active": effective_id,
            "effective": {
                "base_url": effective.get("base_url", ""),
                "model": effective.get("model", ""),
                "source": effective.get("name", ""),
            },
        }


def _configured_llm_values() -> dict:
    """只读取真实配置过的端点/模型（saved + env），不含 schema 默认占位值。

    播种若使用默认占位端点（如 api.openai.com），会在用户从未配置 LLM 时凭空
    造出一个"看起来已配置"的档案，并反过来盖掉环境变量里的真实端点。
    """
    spec = PROVIDER_SPECS["llm"]
    saved = _provider_saved_settings("llm")
    values: dict[str, str] = {}
    for field, env_names in spec["config_env"].items():
        value = saved.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            value = _env_value(*env_names)
        if value is not None and str(value).strip():
            values[field] = str(value).strip()
    return values


def _configured_llm_api_key() -> str:
    spec = PROVIDER_SPECS["llm"]
    saved_secrets = _read_secrets().get("llm", {})
    if isinstance(saved_secrets, dict):
        for field in spec["secret_env"]:
            value = saved_secrets.get(field)
            if value is not None and str(value).strip():
                return str(value).strip()
    return _env_value(*spec["secret_env"]["api_key"])


def _seed_llm_profile(state: dict) -> None:
    """用真实配置过的值播种一个档案，避免用户从零重填。

    没有真实配置时不播种：留下空列表让运行时继续走环境变量，
    也避免在界面上显示一个用户从未填过的占位档案。
    """
    configured = _configured_llm_values()
    base_url = configured.get("base_url", "")
    model = configured.get("model", "")
    if not base_url and not model:
        return

    profile_id = uuid.uuid4().hex[:12]
    state["llm_profiles"] = [{
        "id": profile_id,
        "name": "当前配置",
        "base_url": base_url,
        "model": model,
        "enabled": True,
    }]
    state["active_llm_profile"] = profile_id
    api_key = _configured_llm_api_key()
    if api_key:
        with _SETTINGS_LOCK:
            secrets = _read_secrets()
            secrets.setdefault("llm_profiles", {})[profile_id] = {"api_key": api_key}
            _atomic_write_private_json(SECRETS_FILE, secrets)
    _atomic_write_private_json(SETTINGS_FILE, state)


def save_llm_profile(payload: dict) -> dict:
    """新增或更新一个模型档案；提供 api_key 时一并写入凭据。"""
    if not isinstance(payload, dict):
        raise ValueError("档案必须是对象")
    name = _clean_profile_name(payload.get("name"))
    if not name:
        raise ValueError("档案名称不能为空")
    base_url = _validate_profile_endpoint(payload.get("base_url"))
    model = str(payload.get("model") or "").strip()
    if not model:
        raise ValueError("模型名称不能为空")
    if len(model) > 512:
        raise ValueError("模型名称过长")
    api_key = payload.get("api_key")
    if api_key is not None and not isinstance(api_key, str):
        raise ValueError("API Key 必须是字符串")
    if isinstance(api_key, str) and len(api_key) > 4_096:
        raise ValueError("API Key 过长")

    with _SETTINGS_LOCK:
        state = _normalized_saved_settings()
        raw_id = payload.get("id")
        should_activate = bool(payload.get("activate")) or not state.get("active_llm_profile")
        if raw_id:
            if not _is_valid_profile_id(raw_id):
                raise ValueError("档案 id 非法")
            profile = next((p for p in state["llm_profiles"] if p["id"] == raw_id), None)
            if profile is None:
                raise ValueError("档案不存在")
            profile.update({
                "name": name,
                "base_url": base_url,
                "model": model,
                "enabled": bool(payload.get("enabled", profile.get("enabled", True))),
            })
            profile_id = raw_id
        else:
            if len(state["llm_profiles"]) >= MAX_LLM_PROFILES:
                raise ValueError(f"最多保存 {MAX_LLM_PROFILES} 个档案")
            profile_id = uuid.uuid4().hex[:12]
            state["llm_profiles"].append({
                "id": profile_id,
                "name": name,
                "base_url": base_url,
                "model": model,
                "enabled": bool(payload.get("enabled", True)),
            })
        if should_activate:
            state["active_llm_profile"] = profile_id
        _atomic_write_private_json(SETTINGS_FILE, state)

    if isinstance(api_key, str) and api_key.strip():
        _write_profile_api_key(profile_id, api_key.strip())
    if should_activate:
        # 切换活动档案会把 base_url/model/api_key 落到运行时读取路径上。
        activate_llm_profile(profile_id)
    return list_llm_profiles()


def delete_llm_profile(profile_id: str) -> dict:
    if not _is_valid_profile_id(profile_id):
        raise ValueError("档案 id 非法")
    with _SETTINGS_LOCK:
        state = _normalized_saved_settings()
        before = len(state["llm_profiles"])
        state["llm_profiles"] = [p for p in state["llm_profiles"] if p["id"] != profile_id]
        if len(state["llm_profiles"]) == before:
            raise ValueError("档案不存在")
        if state.get("active_llm_profile") == profile_id:
            # 回退到剩余的第一个档案，否则清空活动标记回到环境变量默认。
            state["active_llm_profile"] = (
                state["llm_profiles"][0]["id"] if state["llm_profiles"] else ""
            )
        _atomic_write_private_json(SETTINGS_FILE, state)
        next_active = state["active_llm_profile"]
        secrets = _read_secrets()
        profiles = secrets.get("llm_profiles")
        if isinstance(profiles, dict):
            profiles.pop(profile_id, None)
            _atomic_write_private_json(SECRETS_FILE, secrets)
    if next_active:
        activate_llm_profile(next_active)
    return list_llm_profiles()


def activate_llm_profile(profile_id: str) -> dict:
    """切换活动档案：把档案写进 providers.llm 与 llm.api_key，运行时立即生效。"""
    if not _is_valid_profile_id(profile_id):
        raise ValueError("档案 id 非法")
    with _SETTINGS_LOCK:
        state = _normalized_saved_settings()
        profile = next((p for p in state["llm_profiles"] if p["id"] == profile_id), None)
        if profile is None:
            raise ValueError("档案不存在")
        state["active_llm_profile"] = profile_id
        provider = state["providers"].setdefault("llm", {})
        provider["base_url"] = profile["base_url"]
        provider["model"] = profile["model"]
        provider["enabled"] = bool(profile.get("enabled", True))
        _atomic_write_private_json(SETTINGS_FILE, state)
        api_key = _profile_api_key(profile_id)
        secrets = _read_secrets()
        if api_key:
            secrets.setdefault("llm", {})["api_key"] = api_key
        else:
            secrets.get("llm", {}).pop("api_key", None)
        _atomic_write_private_json(SECRETS_FILE, secrets)
    return list_llm_profiles()


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
        # 直接改 llm.api_key 时同步回活动档案，避免档案与运行时凭据分叉。
        if provider == "llm" and key == "api_key":
            active = _normalized_saved_settings().get("active_llm_profile")
            if active:
                secrets.setdefault("llm_profiles", {})[active] = {"api_key": value}
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
        if provider == "llm" and key in (None, "api_key"):
            active = _normalized_saved_settings().get("active_llm_profile")
            stored_profiles = secrets.get("llm_profiles")
            if isinstance(stored_profiles, dict):
                if active:
                    stored_profiles.pop(active, None)
                else:
                    secrets.pop("llm_profiles", None)
        _atomic_write_private_json(SECRETS_FILE, secrets)


def clear_profile_secret(profile_id: str) -> None:
    """清除某个档案的 API Key，不在活动档案时只删档案凭据。"""
    if not _is_valid_profile_id(profile_id):
        raise ValueError("档案 id 非法")
    with _SETTINGS_LOCK:
        secrets = _read_secrets()
        profiles = secrets.get("llm_profiles")
        if isinstance(profiles, dict):
            profiles.pop(profile_id, None)
        if _normalized_saved_settings().get("active_llm_profile") == profile_id:
            secrets.get("llm", {}).pop("api_key", None)
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
