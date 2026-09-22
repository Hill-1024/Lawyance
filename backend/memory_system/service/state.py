"""
Shared configuration and process-local state for the conversation memory service.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from collections import OrderedDict
from typing import Any

MEMORY_VERSION = 1
MAX_EVENTS = 200
MAX_FACTS = 80
MAX_FOCUS = 16
MAX_KEYWORDS = 64
MAX_EVENT_CONTENT_CHARS = 3000
MAX_FACT_TEXT_CHARS = 600
MAX_CONTEXT_CHARS = 2800
MAX_ENTITIES = 32
MAX_SEMANTIC_TAGS = 24
MAX_EMBEDDING_TEXT_CHARS = 1200
MAX_EMBEDDING_BATCH_SIZE = 32
MAX_EMBEDDING_CACHE_ITEMS = 512
MAX_EMBEDDING_CACHE_ITEMS_PER_SCOPE = 128
MIN_EMBEDDING_CACHE_ITEMS_PER_SCOPE = 16
MAX_MEMORY_OPS_PER_CALL = 16
MAX_CONVERSATION_CACHE_SCOPES = int(os.getenv("LAWVER_MEMORY_MAX_SCOPES", "512") or 512)
MEMORY_CACHE_TTL_SECONDS = int(os.getenv("LAWVER_MEMORY_CACHE_TTL_SECONDS", str(7 * 24 * 3600)) or 7 * 24 * 3600)
EMBEDDING_MAX_RESPONSE_BYTES = int(os.getenv("MEMORY_EMBEDDING_MAX_RESPONSE_BYTES", str(8 * 1024 * 1024)) or 8 * 1024 * 1024)
EMBEDDING_MODEL_DEFAULT = "Qwen/Qwen3-Embedding-8B"
EMBEDDING_BASE_URL_DEFAULT = "https://api.siliconflow.cn/v1"
EMBEDDING_SCOPE_GLOBAL = "__global__"
FOCUS_DECAY_HALF_LIFE_SECONDS = 14 * 24 * 3600
FOCUS_EFFECTIVE_PRIORITY_FLOOR = 0.45
FOCUS_TOUCH_INTERVAL_SECONDS = 24 * 3600
RAG_DEFAULT_RELEVANCE_THRESHOLD = 1.15
MEMORY_EDIT_REASONS = {"new_information", "correction", "user_preference", "focus_shift", "duplicate_merge"}
MEMORY_FACT_KINDS = {"fact", "constraint", "preference", "goal", "legal_assessment"}

_LOGGER = logging.getLogger("memory_system")
_LOGGER.setLevel(getattr(logging, os.getenv("LAWVER_MEMORY_LOG_LEVEL", "INFO").upper(), logging.INFO))

_RAG_BASE_WEIGHTS: dict[str, float] = {
    "embedding": 3.4,
    "semantic": 3.0,
    "entity": 2.1,
    "lexical": 2.0,
    "fuzzy": 0.8,
    "substring": 1.35,
    "priority": 1.05,
    "confidence": 0.35,
    "recency": 0.3,
    "kind": 0.45,
    "pinned": 1.0,
}
_RAG_PROFILE_MULTIPLIERS: dict[str, dict[str, float]] = {
    "general": {},
    "legal_fact": {
        "embedding": 1.25,
        "semantic": 1.15,
        "entity": 1.35,
        "confidence": 1.2,
        "priority": 0.9,
        "recency": 0.85,
    },
    "architecture_memory": {
        "embedding": 1.1,
        "semantic": 1.2,
        "entity": 1.1,
        "priority": 1.18,
        "pinned": 1.25,
        "fuzzy": 0.9,
    },
    "revision": {
        "embedding": 1.05,
        "semantic": 1.05,
        "priority": 1.15,
        "recency": 1.55,
        "pinned": 1.1,
    },
    "entity_heavy": {
        "embedding": 1.15,
        "entity": 1.45,
        "semantic": 1.05,
        "lexical": 0.95,
    },
}

_MEMORY_DATA_DIR = os.getenv("LAWVER_DATA_DIR") or os.path.join(os.getcwd(), "data")
_MEMORY_DB_PATH = os.getenv("LAWVER_MEMORY_DB") or os.path.join(_MEMORY_DATA_DIR, "memory_cache.sqlite3")

_CONVERSATION_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_CONVERSATION_CACHE_LOCK = threading.RLock()
_SCOPE_LOCKS: dict[str, threading.RLock] = {}
_SCOPE_LOCKS_LOCK = threading.RLock()
_DB_READY = threading.Event()
_DB_READY_LOCK = threading.RLock()

_EMBEDDING_CACHE: OrderedDict[str, OrderedDict[str, list[float]]] = OrderedDict()
_EMBEDDING_LOADED_SCOPES: set[tuple[str, str]] = set()
_EMBEDDING_LOCK = threading.RLock()
_EMBEDDING_FAILURE_UNTIL = 0.0

_ASCII_TOKEN_RE = re.compile(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{1,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_ENTITY_RE = re.compile(
    r"(?:[\u4e00-\u9fffA-Za-z0-9]{1,16}(?:公司|法院|律所|银行|学校|平台|部门|系统|模块|工具|法库|数据库))"
    r"|(?:《[^》]{2,50}》第[一二三四五六七八九十百千万零〇\d]+条)"
    r"|(?:第[一二三四五六七八九十百千万零〇\d]+条)"
    r"|(?:[A-Z][A-Z0-9_.-]{2,32})"
)
_LEADING_TIME_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}[^\]]*]\s*")
_SPACE_RE = re.compile(r"\s+")

_FACT_MARKERS = (
    "记住",
    "以后",
    "后续",
    "我希望",
    "我想",
    "我准备",
    "我们现在",
    "目标",
    "按",
    "采用",
    "严格遵守",
    "必须",
    "禁止",
    "不要",
    "不用",
    "暂时不用",
    "只需要",
    "先",
    "不开工",
    "偏好",
    "架构",
    "设计哲学",
)
_CONSTRAINT_MARKERS = (
    "严格遵守",
    "必须",
    "禁止",
    "不要",
    "不能",
    "不应该",
    "只需要",
    "暂时不用",
    "不开工",
)
_GOAL_MARKERS = ("我准备", "希望", "目标", "我们现在", "按你说", "按这个", "来做")
_DEPRECATION_MARKERS = ("不再", "不需要", "不用", "取消", "改为", "替换为", "不要再", "作废", "删除", "清空", "撤回")
_ASCII_ENTITY_STOPWORDS = {"OK", "NOTE", "COMMENT", "PDF", "DOC", "DOCX", "URL", "HTTP", "HTTPS", "JSON"}
_PROMPT_OVERRIDE_PATTERNS = (
    r"(ignore|disregard|override|bypass|jailbreak).{0,40}(system|developer|instruction|prompt|policy|rule)",
    r"(developer\s*mode|dan\s*mode|jailbreak)",
    r"(忽略|无视|覆盖|绕过|替换).{0,24}(系统|开发者|指令|规则|约束|提示词|prompt)",
    r"(不要|禁止|停止).{0,16}(调用工具|使用工具|检索|标注信源|遵守约束|遵守规则|输出\s*<\s*final_answer)",
    r"<\s*/?\s*(system|developer|assistant|tool|final_answer|think)\b",
)
_PROMPT_DISCLOSURE_RE = re.compile(
    r"(输出|打印|展示|泄露|复述|改写|总结).{0,24}(系统提示|系统指令|开发者指令|工具配置|prompt|system\s*prompt|secret|api[_-]?key)",
    re.IGNORECASE,
)
_PROMPT_DISCLOSURE_NEGATION_RE = re.compile(
    r"(不要|禁止|不能|严禁|不应|不得).{0,10}(输出|打印|展示|泄露|复述|改写|总结)",
    re.IGNORECASE,
)
_SEMANTIC_LEXICON: dict[str, tuple[str, ...]] = {
    "memory_scope": (
        "记忆", "长期", "对话级", "用户级", "全局", "持久", "缓存", "用户侧", "服务端", "本地",
        "同步", "快照", "存储", "历史", "上下文",
    ),
    "attention_control": (
        "注意力", "聚焦", "焦点", "稳定", "集中", "常驻", "每轮", "自动注入", "不会忘", "想起",
        "遗漏", "关注", "提醒", "保障", "保持",
    ),
    "retrieval": (
        "检索", "召回", "查询", "搜索", "模糊", "语义", "向量", "embedding", "rag", "关键词",
        "匹配", "相关", "找回", "联想", "深查",
    ),
    "architecture_boundary": (
        "强解耦", "高复用", "黑箱", "边界", "跨模块", "直接访问", "请求转发", "路由", "中间件",
        "mcps", "模块", "组件", "隔离", "总线", "调度", "入口", "工具转发", "访问工具",
    ),
    "workflow_plan": (
        "方案", "技术方案", "不开工", "先讨论", "实现", "自测", "完成", "继续", "修复",
        "验证", "测试", "重构", "上线", "本地运行",
    ),
    "undo_revision": (
        "撤回", "重发", "修改", "改为", "替换", "修正", "重建", "清空", "删除", "回滚",
        "旧事实", "新事实", "更改", "否定",
    ),
    "payment_fact": (
        "付款", "支付", "付清", "结清", "款项", "价款", "货款", "欠款", "未付", "尚未付款",
        "已经付款", "转账", "收款",
    ),
    "delivery_fact": (
        "交付", "标的物", "履行", "移交", "交货", "收货", "验收", "未交付", "尚未交付",
        "已经交付", "给付",
    ),
    "contract_liability": (
        "合同", "违约", "责任", "民法典", "法条", "案例", "法律", "条文", "第五百七十七条",
        "赔偿", "继续履行", "补救措施",
    ),
    "ocp": (
        "ocp", "输出审查", "格式审查", "信源", "超时", "降级", "保留原文", "后处理",
    ),
}



def _load_embedding_config() -> dict[str, Any] | None:
    enabled = str(os.getenv("MEMORY_EMBEDDING_ENABLED") or "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    api_key = (
        os.getenv("EMBEDDING_API_KEY")
        or os.getenv("MEMORY_EMBEDDING_API_KEY")
        or os.getenv("SILICONFLOW_API_KEY")
    )
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "base_url": (
            os.getenv("EMBEDDING_BASE_URL")
            or os.getenv("MEMORY_EMBEDDING_BASE_URL")
            or EMBEDDING_BASE_URL_DEFAULT
        ).rstrip("/"),
        "model": (
            os.getenv("EMBEDDING_MODEL")
            or os.getenv("MEMORY_EMBEDDING_MODEL")
            or EMBEDDING_MODEL_DEFAULT
        ),
        "timeout": float(os.getenv("MEMORY_EMBEDDING_TIMEOUT", "8") or 8),
        "retry_delay": float(os.getenv("MEMORY_EMBEDDING_RETRY_DELAY", "0.5") or 0.5),
    }

_EMBEDDING_CONFIG: dict[str, Any] | None = _load_embedding_config()

__all__ = [name for name in globals() if not name.startswith("__")]
