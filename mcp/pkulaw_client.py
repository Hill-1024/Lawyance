import json

from RAG.law_data_search import law_exact_search, law_fuzzy_search, law_link_search

"""
本模块仅作为 mcps 的底层实现适配层使用。
上层业务代码必须通过 mcps.use_tools 访问工具，不应直接导入本模块。
"""


def _format_search_result(items):
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


def get_article(title: str, number: str):
    """根据法律名称和条号，精确获取指定法条的完整内容。"""
    print("正在调用本地法库:get_article")
    try:
        result = json.loads(law_exact_search(title or "", number or ""))
    except Exception as exc:
        return json.dumps(
            {"success": False, "message": f"本地法库检索失败: {exc}"},
            ensure_ascii=False,
        )

    if not result.get("success"):
        return json.dumps(
            {
                "success": False,
                "message": result.get("message") or "未找到匹配的法条内容，请检查法律名称和条号是否正确",
            },
            ensure_ascii=False,
        )

    data = result.get("data") or {}
    payload = {
        "success": True,
        "title": data.get("law_name", ""),
        "content": data.get("content", ""),
        "url": data.get("url", ""),
    }

    if not payload["content"]:
        return json.dumps(
            {"success": False, "message": "未找到匹配的条，请修改查询关键词"},
            ensure_ascii=False,
        )

    return json.dumps(payload, ensure_ascii=False)


def search_article(text: str):
    """根据语义检索相关的法律条文。"""
    print("正在调用本地法库:search_article")
    try:
        result = json.loads(law_fuzzy_search(text or "", limit=5))
    except Exception as exc:
        return json.dumps(
            {"success": False, "message": f"搜索失败: {exc}"},
            ensure_ascii=False,
        )

    items = result.get("data") or []
    if not items:
        return json.dumps(
            {
                "success": False,
                "message": result.get("message") or "未检索到相关法条,请调整输入的描述",
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {"success": True, "result": _format_search_result(items)},
        ensure_ascii=False,
    )


def get_linked_content(message: str):
    """根据输入文本返回相关法规信源链接。"""
    print("正在调用本地法库:get_linked_content")
    try:
        result = json.loads(law_link_search(message or "", limit=5))
    except Exception as exc:
        return json.dumps(
            {"success": False, "message": f"获取链接失败: {exc}"},
            ensure_ascii=False,
        )

    if not result.get("success"):
        return json.dumps(
            {
                "success": False,
                "message": result.get("message") or "未找到可匹配的法规信源",
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {"success": True, "text": result.get("text", "")},
        ensure_ascii=False,
    )
