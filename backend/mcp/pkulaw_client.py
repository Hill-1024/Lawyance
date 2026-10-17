"""
模块描述：法条检索适配层。LAWVER_LAW_SOURCE 显式选择本地或自营法库服务；
未设置时沿用 PKU_LAW_SOURCE 选择规则，保留北大法宝开放平台 MCP 接入。
三个来源对外仍是同样三个函数、同样的 JSON 返回形态。

三种数据源：
  · LAWVER_LAW_SOURCE=local：本地法库（RAG/law_data_search + RAG/data）；
  · LAWVER_LAW_SOURCE=remote：自营 HTTP 法库，共用本地检索结果格式；
  · 新开关留空时，PKU_LAW_SOURCE=remote 走北大法宝 MCP，其他值默认本地。
    北大法宝接入文档与端点见 `mcp/pkulaw_mcp.py`。

为什么要显式开关，而不是"有令牌就切远程"：历史 .env 里可能残留已停用的旧令牌，
按存在与否判断会在无人察觉时把产品切到一个连不通或欠费的数据源上。切远程必须
有人明确声明，误配时第一个法条查询就会报出原因，而不是悄悄换数据源作答。
"""

import json
import logging

from mcp import law_service_client, pkulaw_mcp


logger = logging.getLogger(__name__)

# 入参上限：这三个工具的入参由模型生成，正常远小于此；设上限只为挡住病态超长载荷。
_MAX_TITLE_CHARS = 200
_MAX_NUMBER_CHARS = 64
_MAX_TEXT_CHARS = 8000
# 返回条数与本地检索保持一致，避免两种模式的作答风格漂移。
_SEARCH_LIMIT = 5


def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _error(message: str) -> str:
    return _dumps({"success": False, "message": message})


def _clip(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _remote_enabled() -> bool:
    return law_service_client.source() is None and pkulaw_mcp.is_configured()


def _as_mapping_list(payload: object) -> list[dict]:
    """把各服务的返回体归拢成 dict 列表：既可能是数组，也可能是 {data: [...]} 或
    {Data: [...]}（关键词检索用 structuredContent.Data 承载列表）。"""
    if isinstance(payload, dict):
        for key in ("data", "Data", "list", "items", "result"):
            nested = payload.get(key)
            if isinstance(nested, list):
                payload = nested
                break
        else:
            return [payload]
    if not isinstance(payload, list):
        return []
    result = []
    for item in payload:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, list):
            result.extend(child for child in item if isinstance(child, dict))
    return result


def _first_mapping(payload: object) -> dict:
    items = _as_mapping_list(payload)
    return items[0] if items else {}


def _remote_client(service: str) -> pkulaw_mcp.PkulawMcpClient:
    return pkulaw_mcp.PkulawMcpClient(service)


def _format_search_result(items):
    """本地法库条目的展示格式。"""
    lines = []
    for index, item in enumerate(items, start=1):
        law_name = item.get("law_name", "")
        article_number = item.get("article_number", "")
        content = item.get("content", "")
        url = item.get("url", "")
        snippet = content if len(content) <= 220 else f"{content[:220]}..."
        source = f"\n来源: {url}" if url else ""
        lines.append(f"{index}. 《{law_name}》{article_number}\n{snippet}{source}")
    return "\n\n".join(lines)


def _format_remote_search_result(items):
    """法宝条目的展示格式：与本地同构，额外带时效性与效力位阶。

    官方接入文档明确要求引用时优先采用「现行有效」、遇到「已被修改」「废止或失效」
    必须告知用户，所以这两个字段必须随结果一起给出，而不是留到模型去猜。
    """
    lines = []
    for index, item in enumerate(items, start=1):
        title = item.get("title", "")
        # 法宝的 article 已含「第X条」抬头，不再单独拼条号。
        content = str(item.get("article") or "")
        url = str(item.get("url") or "")
        snippet = content if len(content) <= 220 else f"{content[:220]}..."
        meta_bits = [
            f"时效性: {item['timeliness']}" if item.get("timeliness") else "",
            f"效力位阶: {item['effectiveness']}" if item.get("effectiveness") else "",
        ]
        meta = " ｜ ".join(bit for bit in meta_bits if bit)
        meta_line = f"\n{meta}" if meta else ""
        source = f"\n来源: {url}" if url else ""
        lines.append(f"{index}. 《{title}》\n{snippet}{meta_line}{source}")
    return "\n\n".join(lines)


def _local_search_engine():
    """延迟 import：法宝模式下客户机器上可以完全没有 RAG/ 目录。"""
    from RAG import law_data_search

    return law_data_search


def _law_search_engine():
    """自营远程与本地返回相同原始契约，共用下方三个格式化路径。"""
    if law_service_client.source() == "remote":
        return law_service_client
    return _local_search_engine()


def ensure_law_database_ready(*, force_rebuild: bool = False) -> dict:
    """启动期法库准备。

    法宝模式不需要本地库：直接跳过对 RAG/data 的全量扫描与 trigram 建库，
    启动更快，也不要求部署里带上语料。
    """
    if law_service_client.source() == "remote":
        law_service_client.validate_configuration()
        return {
            "rebuilt": False,
            "mode": "remote",
            "file_count": 0,
            "content_sha256": "",
        }
    if _remote_enabled():
        return {
            "rebuilt": False,
            "mode": "remote",
            "file_count": 0,
            "content_sha256": "",
        }
    return _local_search_engine().ensure_law_database_ready(force_rebuild=force_rebuild)


def get_article(title: str, number: str):
    """根据法律名称和条号，精确获取指定法条的完整内容。"""
    title = _clip(title, _MAX_TITLE_CHARS)
    number = _clip(number, _MAX_NUMBER_CHARS)

    try:
        if _remote_enabled():
            return _remote_get_article(title, number)
    except law_service_client.LawServiceError as exc:
        return _error(str(exc))
    return _local_get_article(title, number)


def search_article(text: str):
    """根据语义检索相关的法律条文。"""
    text = _clip(text, _MAX_TEXT_CHARS)

    try:
        if _remote_enabled():
            return _remote_search_article(text)
    except law_service_client.LawServiceError as exc:
        return _error(str(exc))
    return _local_search_article(text)


def get_linked_content(message: str):
    """根据输入文本返回相关法规信源链接。"""
    message = _clip(message, _MAX_TEXT_CHARS)

    try:
        if _remote_enabled():
            return _remote_get_linked_content(message)
    except law_service_client.LawServiceError as exc:
        return _error(str(exc))
    return _local_get_linked_content(message)


def _local_get_article(title: str, number: str):
    logger.info("正在调用法库:get_article")
    try:
        result = json.loads(_law_search_engine().law_exact_search(title or "", number or ""))
    except Exception as exc:
        return _error(f"法库检索失败: {exc}")

    if not result.get("success"):
        return _error(
            result.get("message") or "未找到匹配的法条内容，请检查法律名称和条号是否正确"
        )

    data = result.get("data") or {}
    content = data.get("content", "")
    if not content:
        return _error("未找到匹配的条，请修改查询关键词")

    return _dumps(
        {
            "success": True,
            "title": data.get("law_name", ""),
            "content": content,
            "url": data.get("url", ""),
        }
    )


def _local_search_article(text: str):
    logger.info("正在调用法库:search_article")
    try:
        result = json.loads(_law_search_engine().law_fuzzy_search(text or "", limit=_SEARCH_LIMIT))
    except Exception as exc:
        return _error(f"搜索失败: {exc}")

    if not result.get("success"):
        return _error(result.get("message") or "未检索到相关法条,请调整输入的描述")
    items = result.get("data") or []
    if not items:
        return _error(result.get("message") or "未检索到相关法条,请调整输入的描述")

    return _dumps({"success": True, "result": _format_search_result(items)})


def _local_get_linked_content(message: str):
    logger.info("正在调用法库:get_linked_content")
    try:
        result = json.loads(
            _law_search_engine().law_link_search(message or "", limit=_SEARCH_LIMIT)
        )
    except Exception as exc:
        return _error(f"获取链接失败: {exc}")

    if not result.get("success"):
        return _error(result.get("message") or "未找到可匹配的法规信源")

    return _dumps({"success": True, "text": result.get("text", "")})


def _remote_get_article(title: str, number: str):
    logger.info("正在调用北大法宝:get_article")
    if not title or not number:
        return _error("需要同时提供法律名称与条号，例如《民法典》与「第五百七十七条」")

    try:
        payload = _remote_client("law_search").call_tool(
            "get_article", {"title": title, "number": number}
        )
    except pkulaw_mcp.PkulawMcpError as exc:
        logger.warning("北大法宝 get_article 失败 | %s", exc)
        return _error(str(exc))

    item = _first_mapping(payload)
    content = str(item.get("article") or "").strip()
    if not content:
        return _error("未找到匹配的法条内容，请检查法律名称和条号是否正确")

    result = {
        "success": True,
        "title": str(item.get("title") or title),
        "content": content,
        "url": str(item.get("url") or ""),
    }
    # 时效性直接决定条文能不能引，随结果一起给出。
    if item.get("timeliness"):
        result["timeliness"] = str(item["timeliness"])
    return _dumps(result)


def _remote_search_article(text: str):
    logger.info("正在调用北大法宝:search_article")
    if not text:
        return _error("请输入要检索的案情描述或法律问题")

    try:
        payload = _remote_client("law_search").call_tool(
            "search_article", {"text": text, "size": _SEARCH_LIMIT}
        )
    except pkulaw_mcp.PkulawMcpError as exc:
        logger.warning("北大法宝 search_article 失败 | %s", exc)
        return _error(str(exc))

    items = _as_mapping_list(payload)
    if not items:
        return _error("未检索到相关法条,请调整输入的描述")

    return _dumps(
        {"success": True, "result": _format_remote_search_result(items[:_SEARCH_LIMIT])}
    )


def _remote_get_linked_content(message: str):
    logger.info("正在调用北大法宝:get_linked_content")
    if not message:
        return _error("请输入需要加信源链接的文本")

    try:
        payload = _remote_client("doc_link").call_tool(
            "get_linked_content", {"message": message}
        )
    except pkulaw_mcp.PkulawMcpError as exc:
        logger.warning("北大法宝 get_linked_content 失败 | %s", exc)
        return _error(str(exc))

    text = _linked_text(payload)
    if not text:
        return _error("未找到可匹配的法规信源")

    return _dumps({"success": True, "text": text})


def _linked_text(payload: object) -> str:
    """法宝超链返回 [{type: "text", text: "<带 Markdown 链接的正文>"}]。"""
    if isinstance(payload, str):
        return payload.strip()
    parts = []
    for item in _as_mapping_list(payload):
        text = str(item.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)
