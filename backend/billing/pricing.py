"""
模块描述：计价目录与套餐定义——「一次调用值多少 credits」的唯一出处。

单位：内部一律用 micro-credit 整数记账（1 credit = 1000 micro），避免任何浮点误差。
对外展示时再除成两位小数。

计价公式（默认值，可被环境变量覆盖）：
    模型  credits = (prompt × P + completion × C) / 1000 × profile_weight
    工具  每次固定价，可按工具名覆盖
    文档  每万字符一个价，有下限

计费倍率把「按量」和「订阅」的差距压缩成一个数字：同一刀用量，订阅按倍率打折。
这样不用维护两套价格表，套餐到期后只要改这一个字段。
"""

from __future__ import annotations

import os
from typing import Any


MICRO = 1000  # 1 credit = 1000 micro-credit


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ─── 单价 ─────────────────────────────────────────────────────────────────

# 每 1000 token 的 credits。输出比输入贵：两者成本结构不同。
PRICE_PROMPT_PER_1K = _env_float("LAWVER_PRICE_PROMPT_PER_1K", 0.10)
PRICE_COMPLETION_PER_1K = _env_float("LAWVER_PRICE_COMPLETION_PER_1K", 0.30)

# 每次工具调用。默认价覆盖未知工具；具名工具按名字覆盖。
PRICE_TOOL_DEFAULT = _env_float("LAWVER_PRICE_TOOL_DEFAULT", 0.5)
PRICE_TOOL_BY_NAME: dict[str, float] = {
    # 外部检索类：命中第三方配额，单价高一些。
    "web_search": 1.0,
    "searxng_search": 1.0,
    # 法律数据类：走授权数据源，成本最高。
    "deli_law_search": 2.0,
    "pkulaw_search": 2.0,
    "qcc_company_search": 2.0,
}

# 文档解析：每 1 万字符，另有下限，避免小文件被算成 0。
PRICE_DOCUMENT_PER_10K_CHARS = _env_float("LAWVER_PRICE_DOCUMENT_PER_10K", 0.2)
PRICE_DOCUMENT_MIN = _env_float("LAWVER_PRICE_DOCUMENT_MIN", 0.1)

# 充值比价：1 元 = 多少 credits。
CREDITS_PER_YUAN = _env_float("LAWVER_CREDITS_PER_YUAN", 12.0)


def credits(value: float) -> int:
    """把 credits 数额转成 micro-credit 整数。"""
    return int(round(value * MICRO))


def as_credits(micro: int) -> float:
    return round(micro / MICRO, 2)


# ─── 套餐与计费倍率 ───────────────────────────────────────────────────────

# multiplier 越小，同一刀用量扣得越少（即订阅越长约等于打折）。
# 按量充值不做折扣，它本身就是「用多少付多少」的基准。
BILLING_MULTIPLIERS: dict[str, float] = {
    "metered": 1.0,
    "monthly": 0.8,
    "yearly": 0.65,
    "business": 0.6,
}


def multiplier_for(plan: str, billing_cycle: str, override: float | None = None) -> float:
    """账号的实际计费倍率：账号级覆盖 > 套餐级默认。"""
    if override is not None and override > 0:
        return float(override)
    if plan == "business":
        return BILLING_MULTIPLIERS["business"]
    return BILLING_MULTIPLIERS.get(billing_cycle, 1.0)


# 四档套餐。价格单位元；yearly 按月价 ×10（送两个月）。
# features 直接给前端定价页用，改这里就能改页面。
PLANS: list[dict[str, Any]] = [
    {
        "id": "metered",
        "name": "按量充值",
        "tagline": "不订阅，用多少付多少",
        "price_month": 0,
        "price_year": 0,
        "monthly_credits": 0,
        "multiplier": BILLING_MULTIPLIERS["metered"],
        "max_online": 1,
        "highlights": [
            "按实际用量扣费，无月费",
            f"1 元 = {CREDITS_PER_YUAN:g} credits，余额不过期",
            "可随时升级到订阅套餐",
        ],
    },
    {
        "id": "go",
        "name": "Go",
        "tagline": "个人日常法律事务",
        "price_month": 59,
        "price_year": 590,
        "monthly_credits": 600,
        "multiplier": BILLING_MULTIPLIERS["monthly"],
        "max_online": 1,
        "highlights": [
            "每月 600 credits",
            "1 台设备同时在线",
            "法条检索与文书起草",
            "单文档上限 50MB",
        ],
    },
    {
        "id": "pro",
        "name": "Pro",
        "tagline": "执业律师的日常主力",
        "price_month": 199,
        "price_year": 1990,
        "monthly_credits": 2400,
        "multiplier": BILLING_MULTIPLIERS["monthly"],
        "max_online": 3,
        "recommended": True,
        "highlights": [
            "每月 2,400 credits",
            "3 台设备同时在线",
            "计划与求解模式、高级输出审查",
            "可自定义技能",
            "单文档上限 100MB",
        ],
    },
    {
        "id": "max",
        "name": "Max",
        "tagline": "高强度办案与团队协作",
        "price_month": 699,
        "price_year": 6990,
        "monthly_credits": 9000,
        "multiplier": BILLING_MULTIPLIERS["monthly"],
        "max_online": 5,
        "highlights": [
            "每月 9,000 credits",
            "5 台设备同时在线，最多 3 个任务并行",
            "可接入 1 个外部连接器",
            "优先队列，单文档上限 200MB",
        ],
    },
    {
        "id": "business",
        "name": "Business",
        "tagline": "律所与法务团队",
        "price_month": None,
        "price_year": None,
        "monthly_credits": None,
        "multiplier": BILLING_MULTIPLIERS["business"],
        "max_online": None,
        "highlights": [
            "credits 池化，按团队规模议定",
            "子账号与预算分配",
            "各子账号用量与余额独立可见",
            "外部连接器不限，专属支持",
        ],
    },
]


def plan_catalog() -> list[dict[str, Any]]:
    """给定价页用的套餐目录（含计费口径说明，不暴露任何密钥或内部开关）。"""
    return [
        {
            **plan,
            "credits_per_yuan": CREDITS_PER_YUAN,
        }
        for plan in PLANS
    ]


def plan_by_id(plan_id: str) -> dict[str, Any] | None:
    for plan in PLANS:
        if plan["id"] == plan_id:
            return plan
    return None


def tool_price(name: str) -> float:
    return PRICE_TOOL_BY_NAME.get(name, PRICE_TOOL_DEFAULT)


def model_credits(prompt_tokens: int, completion_tokens: int, weight: float = 1.0) -> float:
    """一次模型调用的 credits（未乘计费倍率）。"""
    raw = (
        max(prompt_tokens, 0) * PRICE_PROMPT_PER_1K
        + max(completion_tokens, 0) * PRICE_COMPLETION_PER_1K
    ) / 1000
    return raw * (weight if weight > 0 else 1.0)


def document_credits(chars: int) -> float:
    if chars <= 0:
        return 0.0
    return max(PRICE_DOCUMENT_PER_10K_CHARS * chars / 10000, PRICE_DOCUMENT_MIN)
