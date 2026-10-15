"""
模块描述：得理案例检索客户端（新版开放平台），封装认证请求、异常处理和案例匹配工具。

【2026-10 接口变更】得理把开放平台从「appid + secret」换成了标准 API Key：

  旧：https://openapi.delilegal.com/api/qa/v3/search/queryListCase
      headers: {appid, secret}
      body:    {condition: {keywordArr: [...]}, caseYearStart, caseYearEnd, ...}

  新：https://platform.delilegal.com/api/v1/generice/case/list
      headers: {authorization: Bearer sk-xxxx}
      body:    {query: "自然语言案情描述", pageNo, pageSize, sortField, sortOrder}

两个实质差别，不只是换地址：

  1. **凭据**：一个人一个 API Key，在开放平台「API Keys」页自助创建，
     不再是需要企业资质才能申请到 appid/secret。个人账号也能用。
  2. **检索方式**：旧接口收关键词数组，新接口收**自然语言 query**，
     是语义检索 —— 所以这里把 LLM 给的关键词拼成一句查询语。

计费：¥0.2 / 次（案例检索 MCP 云服务，以官方当期定价为准）。
"""
import requests
import json
import logging
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(".env")

# 响应体读取上限：得理是受信上游，但仍按其余外部客户端同一标准限长，防止异常响应耗尽内存。
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024

# 单次返回的案例条数上限。案例正文很长，条数给太多会挤爆上下文。
_MAX_CASES = 8

_DEFAULT_ENDPOINT = "https://platform.delilegal.com/api/v1/generice/case/list"
_ALLOWED_HOST = "platform.delilegal.com"


# 得理的业务错误码 → 人话。它 HTTP 层可能返回 200，真正的错误只在正文的
# code/msg 里，所以这张表是排查的关键（只看状态码会被骗过去）。
_DELI_CODE_HINTS = {
    10001: "API Key 无效或已删除 —— 去开放平台「API Keys」页确认",
    10002: "API Key 已过期",
    10003: "该接口未开通权限",
    10004: "余额不足 —— 去开放平台「余额」页充值",
    10005: "并发超限",
}

# HTTP 状态码 → 人话（业务错误码之外的情况）
_HTTP_HINTS = {
    400: "请求被拒绝（参数或接口路径不对）",
    401: "API Key 无效或缺失",
    403: "API Key 权限不足，或余额不足",
    404: "接口地址不存在（端点可能已变更）",
    429: "调用过于频繁，请降低频率",
    500: "得理服务端错误",
    502: "得理服务暂时不可用",
    503: "得理服务暂时不可用",
}


class DELINotConfiguredError(RuntimeError):
    """DELI_API_KEY 尚未配置（环境变量或管理后台）。"""


class DELIClientError(RuntimeError):
    """调用得理过程中的可预期错误（凭据、地址、业务码、网络）。"""


def _load_api_key() -> str:
    """调用期读取凭据：既不因缺配置阻断整个后端启动，也让管理后台热更新即时生效。"""
    api_key = (os.getenv("DELI_API_KEY") or "").strip()
    if not api_key:
        raise DELINotConfiguredError("得理法搜尚未配置 API Key")
    return api_key


def _describe_business_error(payload: dict) -> str:
    """把得理返回的业务错误说清楚。"""
    code = payload.get("code")
    reason = payload.get("msg") or payload.get("message") or "未知原因"
    try:
        hint = _DELI_CODE_HINTS.get(int(code)) if code is not None else None
    except (TypeError, ValueError):
        hint = None
    msg = "案例检索服务拒绝请求：%s" % reason
    if hint:
        msg += "（%s）" % hint
    elif code not in (None, 0):
        msg += "（错误码 %s）" % code
    return msg


def _describe_http_error(status: int, response) -> str:
    """HTTP 错误连同响应正文一起说清楚 —— 正文里往往写着真正的原因。"""
    hint = _HTTP_HINTS.get(status, "未知错误")
    detail = ""
    try:
        raw = (response.text or "").strip()
        if raw:
            detail = raw.replace("\n", " ")[:200]
    except Exception:
        pass
    msg = "案例检索服务返回 %d：%s" % (status, hint)
    if detail:
        msg += "。服务端说明：%s" % detail
    return msg


class DELIClient:
    """得理案例检索客户端（新版 API Key 鉴权）。"""

    def __init__(self, api_key: str | None = None):
        self.api_key = (api_key if api_key is not None else _load_api_key()).strip()
        if not self.api_key:
            raise DELINotConfiguredError("得理法搜尚未配置 API Key")

        self.endpoint = (os.getenv("DELI_ENDPOINT") or _DEFAULT_ENDPOINT).strip()
        parsed = urlparse(self.endpoint)
        # 与其余外部客户端一致：只允许官方 https 地址，避免把凭据发给任意主机。
        if (
            parsed.scheme != "https"
            or parsed.hostname != _ALLOWED_HOST
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise DELIClientError("得理服务地址配置非法")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def search_cases(
        self,
        query: str,
        page_no: int = 1,
        page_size: int = _MAX_CASES,
        sort_field: str = "correlation",
        sort_order: str = "desc",
    ) -> dict:
        """调用案例检索接口，返回原始 JSON（dict）。异常统一抛 DELIClientError。"""
        body = {
            "query": query,
            "pageNo": page_no,
            "pageSize": page_size,
            "sortField": sort_field,
            "sortOrder": sort_order,
        }

        try:
            response = requests.post(
                self.endpoint,
                headers=self.headers,
                json=body,
                timeout=30,
                stream=True,
            )
        except requests.exceptions.RequestException as exc:
            raise DELIClientError("案例检索网络请求失败：%s" % exc) from exc

        try:
            if response.status_code != 200:
                raise DELIClientError(_describe_http_error(response.status_code, response))

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    raise DELIClientError("案例检索响应过大，已中止读取")
                chunks.append(chunk)
        finally:
            response.close()

        raw = b"".join(chunks)
        try:
            payload = json.loads(raw.decode(response.encoding or "utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DELIClientError("案例检索响应解析失败：%s" % exc) from exc

        if not isinstance(payload, dict):
            raise DELIClientError("案例检索响应格式异常")

        # 业务层失败：即使 HTTP 200 也要判。
        if payload.get("success") is False:
            raise DELIClientError(_describe_business_error(payload))

        return payload


def build_client() -> DELIClient:
    return DELIClient()


def match_legal_case(
    keywords: list[str],
    start_year: str = "2020-12-22",
    end_year: str = "2025-12-22",
):
    """根据查询语义检索类似案例。

    保持与工具层一致的签名。两点说明：

      · keywords 是 LLM 给出的关键语句列表，这里**拼成一句自然语言 query** ——
        新版得理接口是语义检索，收的是"案情描述/争议焦点/法律问题"，
        而不是旧版的关键词数组。
      · start_year / end_year **当前接口不支持按时间过滤**（新版只提供
        pageNo/pageSize/sortField/sortOrder）。参数保留是为了不破坏工具 schema
        与既有调用方，实际不参与请求；需要时间维度时由模型按判决日期自行筛选。
    """
    logger.debug("调用工具 match_legal_case")

    try:
        client = build_client()
    except DELINotConfiguredError:
        return {
            "success": False,
            "message": "案例检索服务未配置：请先在管理后台「得理法搜」中填写 API Key"
                       "（或在环境变量中设置 DELI_API_KEY）。",
        }

    # 把关键词拼成查询语句。得理是语义检索，自然语言比逗号分隔的关键词效果好。
    parts = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    if not parts:
        return {"success": False, "message": "案例检索需要至少一个查询关键词"}
    query = " ".join(parts)

    try:
        payload = client.search_cases(query, page_size=_MAX_CASES)
    except DELIClientError as exc:
        # 具体原因原样透出，不吞成"请稍后重试" —— 那会让
        # "没填 API Key""余额不足"这种一眼能修的问题看起来像服务故障。
        logger.warning("得理案例检索失败 | %s", exc)
        return {"success": False, "message": str(exc)}

    body = payload.get("body") or {}
    items = body.get("data") if isinstance(body.get("data"), list) else []
    if not items:
        return {"success": False, "message": "没有找到匹配的案例，请调整查询描述"}

    result = []
    for item in items[:_MAX_CASES]:
        if not isinstance(item, dict):
            continue
        # 顺带把法院、案号带出来：法律场景里这两个比正文更能支撑"可核验"。
        source = item.get("title") or ""
        court = item.get("court") or ""
        case_number = item.get("caseNumber") or ""
        if court or case_number:
            source = "%s（%s%s）" % (
                source,
                court,
                (" " + case_number) if case_number else "",
            )
        result.append({
            "source": source,
            "judgementDate": item.get("judgementDate") or "",
            "content": item.get("content") or "",
        })

    return json.dumps({"success": True, "data": result}, ensure_ascii=False)


if __name__ == "__main__":
    # 手工联调：DELI_API_KEY=sk-xxx python -m mcp.deli_client
    print(match_legal_case(keywords=["上班途中出车祸工伤保险的相关类案"]))
