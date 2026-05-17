"""
模块描述：业务工具转发中间件，统一暴露法律检索、文件处理、企业查询和记忆工具。
"""

from mcp.deli_client import match_legal_case
from mcp.pkulaw_client import get_article, search_article, get_linked_content
from mcp.PDF_processor import pdf_text_reader, pdf_commit_by_sentence
from mcp.word_annotator import word_reader, word_writer
from mcp.qcc_client import get_company_profile,get_listing_info,get_contact_info,get_shareholder_info,get_company_registration_info,get_key_personnel,get_external_investments
from mcp.memory_client import (
    clear_conversation_memory,
    inspect_conversation_memory,
    remember_conversation_turn,
    retrieve_conversation_memory,
    sync_conversation_memory,
    update_conversation_memory,
)
import os
import json


class WorkspacePathError(ValueError):
    pass


def _is_within_directory(path, directory):
    abs_path = os.path.abspath(path)
    abs_dir = os.path.abspath(directory)
    return abs_path == abs_dir or abs_path.startswith(abs_dir + os.sep)


def _validate_workspace_scope(workspace_scope):
    if not workspace_scope or os.path.isabs(workspace_scope):
        raise WorkspacePathError("无法获取当前工作区作用域。")
    parts = workspace_scope.replace("\\", "/").split("/")
    if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
        raise WorkspacePathError("工作区作用域格式非法。")
    return os.path.join(*parts)


def _workspace_dir(root, workspace_scope):
    return os.path.abspath(os.path.join(root, _validate_workspace_scope(workspace_scope)))


def resolve_workspace_file(input_path, workspace_scope, allowed_roots=("TEMP", "Result")):
    if not input_path:
        raise WorkspacePathError("未提供文件路径。")

    normalized_path = str(input_path).replace("\\", "/").strip()
    if os.path.isabs(normalized_path):
        raise WorkspacePathError("不允许使用绝对路径。")

    candidate = os.path.abspath(normalized_path)
    allowed_dirs = [_workspace_dir(root, workspace_scope) for root in allowed_roots]
    if not any(_is_within_directory(candidate, directory) for directory in allowed_dirs):
        raise WorkspacePathError("文件路径不属于当前工作区。")
    return candidate


def get_result_path(input_path, workspace_scope):
    source_path = resolve_workspace_file(input_path, workspace_scope, allowed_roots=("TEMP", "Result"))
    filename = os.path.basename(source_path)
    base, ext = os.path.splitext(filename)
    if not base.endswith("_lawyance"):
        base = f"{base}_lawyance"

    result_dir = os.path.join("Result", _validate_workspace_scope(workspace_scope))
    os.makedirs(result_dir, exist_ok=True)
    return os.path.join(result_dir, f"{base}{ext}").replace("\\", "/")


tools = [
    {
        "type": "function",
        "function": {
            "name": "match_legal_case",
            "description": "查询法律案例知识库。当需要根据用户语义和时间范围获取类似案例、判决结果或司法实践参考时，必须调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "用于案例检索的关键语句列表，应提取自用户查询的核心意图，如['案件类型'、'争议焦点']，关键语句数量应小于三个"
                    },
                    "start_year": {
                        "type": "string",
                        "description": "案例查询的起始时间，格式为YYYY-MM-DD，用于筛选此日期之后判决的案例。如不指定，默认为2020-12-22。"
                    },
                    "end_year": {
                        "type": "string",
                        "description": "案例查询的截止时间，格式为YYYY-MM-DD，用于筛选此日期之前判决的案例。如不指定，默认为2025-12-22。"
                    },
                },
                "required": ["keywords"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_article",
            "description": "查询法律知识库。当需要根据法律名称和条号，精确获取指定法条的完整内容时，必须调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "具体的法律名称，应提取自用户查询的核心意图"
                    },
                    "number": {
                        "type": "string",
                        "description": "具体的法条号，应提取自用户查询的核心意图，形式如['第九条','第十七条']"
                    }
                },
                "required": ["title", "number"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "search_article",
            "description": "查询法律知识库。当需要通过自然语言描述，语义检索相关的法律条文时，必须调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "语义检索关键词或自然语言描述，应提取自用户查询的核心意图"
                    },
                },
                "required": ["query"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "get_linked_content",
            "description": "获取相关法规信息的来源链接，当出现法规条文、法律概念和相关术语，必须调用此工具确认来源!!!",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "包含法规条文、法律概念和相关术语的文本"
                    },
                },
                "required": ["message"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "pdf_text_reader",
            "description": "解析PDF文件并返回JSON对象，内容为每句文本及其坐标，为后续批注提供坐标参数。当用户要求批注或修改PDF合同时，应先调用此工具读取内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "PDF文件的路径"
                    }
                },
                "required": ["pdf_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pdf_commit_by_sentence",
            "description": "根据提供的文件路径、文本内容和坐标参数，对PDF文件进行批注。通常在调用pdf_text_reader获取坐标后使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pdf_path": {
                        "type": "string",
                        "description": "PDF文件的路径"
                    },
                    "note_text": {
                        "type": "string",
                        "description": "批注的具体文本内容"
                    },
                    "page_index": {
                        "type": "integer",
                        "description": "页码索引（从0开始）"
                    },
                    "sentence_index": {
                        "type": "integer",
                        "description": "句子索引（从0开始）"
                    }
                },
                "required": ["pdf_path", "note_text", "page_index", "sentence_index"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "word_reader",
            "description": "根据文件路径读取docx文档，并返回包含段落索引和内容的JSON格式数据。当用户要求批注或修改Word合同时，应先调用此工具读取内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Word文档(docx)的路径"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "word_writer",
            "description": "根据段落索引和文本内容，对Word文档进行批注。通常在调用word_reader获取段落索引后使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Word文档(docx)的路径"
                    },
                    "index": {
                        "type": "integer",
                        "description": "需要批注的段落索引（从0开始）"
                    },
                    "text": {
                        "type": "string",
                        "description": "批注的具体文本内容"
                    }
                },
                "required": ["file_path", "index", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_workspace_files",
            "description": "列出当前对话工作区（Workspace）中的所有文件。当用户上传了多个文件，或者你需要知道当前有哪些文件可供读取或处理时，调用此工具。返回包含文件名和路径的列表。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_conversation_memory",
            "description": "查询当前对话级长期记忆。当用户问题依赖此前对话中的目标、约束、偏好、案件事实或工作边界，而当前上下文不足时，调用此工具进行深查。基础注意力上下文会由系统自动注入，此工具仅用于补充召回。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "需要在当前对话记忆中检索的自然语言问题或关键词"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回的记忆条数，默认8"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_conversation_memory",
            "description": "查看当前对话的事实库、焦点和最近事件，返回可用于修改记忆的 fact/focus/event id。当你准备新增、修正、废弃记忆，或不确定旧事实是否已存在时，必须先调用此工具确认当前库状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "可选。用于筛选相关记忆的自然语言问题或关键词。"
                    },
                    "include_deprecated": {
                        "type": "boolean",
                        "description": "是否包含已废弃事实。只有在判断修正链或回滚时设为 true。"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回的事实条数，默认20，最大40。"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_conversation_memory",
            "description": "修改当前对话级事实库。仅在用户明确提供新的稳定事实、偏好、约束、案件焦点，或明确修正/否定旧事实时调用。不要把普通问题、临时推理、法条检索结果或无来源总结写入记忆。",
            "parameters": {
                "type": "object",
                "properties": {
                    "operations": {
                        "type": "array",
                        "description": "记忆修改操作列表。复杂信息可拆成多条操作，不设三条硬上限；每条都必须有 source_text 证据。",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {
                                    "type": "string",
                                    "enum": ["create_fact", "update_fact", "deprecate_fact", "update_focus", "deprecate_focus"],
                                    "description": "create_fact 新增事实；update_fact 用新事实替换旧 fact；deprecate_fact 废弃旧 fact；update_focus 新增或更新焦点；deprecate_focus 废弃旧焦点。"
                                },
                                "target_id": {
                                    "type": "string",
                                    "description": "update_fact/deprecate_fact/update_focus/deprecate_focus 修改已有条目时填写目标 id。"
                                },
                                "text": {
                                    "type": "string",
                                    "description": "create_fact/update_focus 的文本。必须忠实于用户明示信息。"
                                },
                                "new_text": {
                                    "type": "string",
                                    "description": "update_fact 的新事实文本。"
                                },
                                "kind": {
                                    "type": "string",
                                    "enum": ["fact", "constraint", "preference", "goal", "legal_assessment"],
                                    "description": "事实类型。案件事实用 fact；用户偏好用 preference；稳定约束用 constraint。"
                                },
                                "focus_type": {
                                    "type": "string",
                                    "enum": ["case", "dialog"],
                                    "description": "update_focus 使用。案件主线用 case，当前任务用 dialog。"
                                },
                                "source_text": {
                                    "type": "string",
                                    "description": "本次修改的原文证据，必须来自当前用户明确表达或 inspect_conversation_memory 返回的既有事实。"
                                },
                                "reason": {
                                    "type": "string",
                                    "enum": ["new_information", "correction", "user_preference", "focus_shift", "duplicate_merge"],
                                    "description": "修改原因。"
                                },
                                "confidence": {
                                    "type": "number",
                                    "description": "置信度，0 到 1。"
                                },
                                "priority": {
                                    "type": "number",
                                    "description": "优先级，0 到 1。"
                                }
                            },
                            "required": ["op", "source_text", "reason"]
                        }
                    }
                },
                "required": ["operations"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_company_profile",
            "description": "查询企业的简介信息，包括企业名称、简介，当需要获取企业相关信息时，必须调用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "具体的企业名称，应提取自用户查询的核心意图"
                    },
                },
                "required": ["company"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "get_company_registration_info",
            "description": "查询企业的核心登记信息，包括法定代表人、注册资本、成立时间等，当需要获取企业相关信息时，必须调用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "具体的企业名称，应提取自用户查询的核心意图"
                    },
                },
                "required": ["company"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "get_contact_info",
            "description": "查询企业的联系方式信息，包括电话号码、邮箱、企业网站等，当需要获取企业相关联系方式时，必须调用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "具体的企业名称，应提取自用户查询的核心意图"
                    },
                },
                "required": ["company"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "get_external_investments",
            "description": "查询企业对外投资信息，包括被投资企业名称、持股比例等。当需要获取企业对外投资信息时，必须调用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "具体的企业名称，应提取自用户查询的核心意图"
                    },
                },
                "required": ["company"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "get_key_personnel",
            "description": "查询企业主要管理人员信息，包括姓名、职务等。当需要获取企业主要管理人员信息时，必须调用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "具体的企业名称，应提取自用户查询的核心意图"
                    },
                },
                "required": ["company"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "get_listing_info",
            "description": "查询企业的上市信息，包括股票代码、上市交易所、总市值等。当需要获取企业上市信息时，必须调用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "具体的企业名称，应提取自用户查询的核心意图"
                    },
                },
                "required": ["company"]
            }
        }

    },
    {
        "type": "function",
        "function": {
            "name": "get_shareholder_info",
            "description": "查询企业股东构成信息，包括投资人姓名、持股比例等。当需要获取企业股东构成信息时，必须调用此工具",
            "parameters": {
                "type": "object",
                "properties": {
                    "company": {
                        "type": "string",
                        "description": "具体的企业名称，应提取自用户查询的核心意图"
                    },
                },
                "required": ["company"]
            }
        }

    },
]


def format_tool_descriptions(tool_defs=None):
    selected_tools = tool_defs or tools
    return "\n".join(
        f"- {tool['function']['name']}: {tool['function']['description']}"
        for tool in selected_tools
    )


def _coerce_arguments(function_name, arguments):
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            if function_name == "search_article":
                arguments = {"query": arguments}
            elif function_name == "get_linked_content":
                arguments = {"message": arguments}
            elif function_name == "pdf_text_reader":
                arguments = {"pdf_path": arguments}
            elif function_name == "word_reader":
                arguments = {"file_path": arguments}
            elif function_name == "match_legal_case":
                arguments = {"keywords": [arguments]}
            elif function_name == "retrieve_conversation_memory":
                arguments = {"query": arguments}
            elif function_name == "inspect_conversation_memory":
                arguments = {"query": arguments}
            elif function_name == "get_article":
                parts = arguments.strip().rsplit(" ", 1)
                if len(parts) == 2 and parts[1].startswith("第"):
                    arguments = {"title": parts[0], "number": parts[1]}
                else:
                    arguments = {"title": arguments, "number": ""}
            elif function_name == "pdf_commit_by_sentence":
                arguments = {"pdf_path": arguments}
            elif function_name == "word_writer":
                arguments = {"file_path": arguments}
            elif function_name in {
                "get_company_profile",
                "get_company_registration_info",
                "get_contact_info",
                "get_external_investments",
                "get_key_personnel",
                "get_listing_info",
                "get_shareholder_info",
            }:
                arguments = {"company": arguments}

    if not isinstance(arguments, dict):
        return {}

    return arguments


def _list_workspace_files(workspace_scope):
    try:
        safe_scope = _validate_workspace_scope(workspace_scope)
    except WorkspacePathError:
        return "无法获取当前工作区作用域，无法列出文件。"

    files = []
    for base_dir, file_type in (("TEMP", "upload"), ("Result", "generated")):
        workspace_dir = os.path.join(base_dir, safe_scope)
        if not os.path.exists(workspace_dir):
            continue

        for file_name in os.listdir(workspace_dir):
            file_path = os.path.join(workspace_dir, file_name)
            if os.path.isfile(file_path):
                files.append({
                    "name": file_name,
                    "path": file_path.replace('\\', '/'),
                    "type": file_type,
                })

    if not files:
        return "当前工作区没有任何文件。"

    return json.dumps(files, ensure_ascii=False)


def _dispatch_tool(function_name, arguments, workspace_scope):
    if function_name == "list_workspace_files":
        return _list_workspace_files(workspace_scope)
    if function_name == "retrieve_conversation_memory":
        return retrieve_conversation_memory(
            workspace_scope,
            arguments.get("query", ""),
            arguments.get("limit", 8),
        )
    if function_name == "inspect_conversation_memory":
        return inspect_conversation_memory(
            workspace_scope,
            arguments.get("query", ""),
            bool(arguments.get("include_deprecated", False)),
            arguments.get("limit", 20),
        )
    if function_name == "update_conversation_memory":
        return update_conversation_memory(
            workspace_scope,
            arguments.get("operations", []),
        )
    if function_name == "sync_conversation_memory":
        return sync_conversation_memory(
            workspace_scope,
            arguments.get("snapshot"),
            arguments.get("messages"),
            arguments.get("mode"),
            arguments.get("expected_revision"),
            arguments.get("memory_conflict_strategy"),
        )
    if function_name == "remember_conversation_turn":
        return remember_conversation_turn(
            workspace_scope,
            arguments.get("user_message", ""),
            arguments.get("assistant_message", ""),
            arguments.get("turn_id"),
        )
    if function_name == "clear_conversation_memory":
        return clear_conversation_memory(workspace_scope)
    if function_name == "match_legal_case":
        return match_legal_case(arguments.get("keywords"), arguments.get("start_year"), arguments.get("end_year"))
    if function_name == "get_article":
        return get_article(arguments.get("title"), arguments.get("number"))
    if function_name == "search_article":
        return search_article(arguments.get("query"))
    if function_name == "get_linked_content":
        return get_linked_content(arguments.get("message"))
    if function_name == "pdf_text_reader":
        path = arguments.get("pdf_path") or arguments.get("file_path") or arguments.get("path")
        if not path:
            return "错误：未提供PDF文件路径。"
        try:
            safe_path = resolve_workspace_file(path, workspace_scope, allowed_roots=("TEMP", "Result"))
        except WorkspacePathError as e:
            return f"错误：{e}"
        return pdf_text_reader(safe_path)
    if function_name == "pdf_commit_by_sentence":
        path = arguments.get("pdf_path") or arguments.get("file_path") or arguments.get("path")
        if not path:
            return "错误：未提供PDF文件路径。"
        try:
            safe_path = resolve_workspace_file(path, workspace_scope, allowed_roots=("TEMP", "Result"))
            output_path = get_result_path(path, workspace_scope)
        except WorkspacePathError as e:
            return f"错误：{e}"
        success, out_path = pdf_commit_by_sentence(
            safe_path,
            arguments.get("note_text"),
            arguments.get("page_index", 0),
            arguments.get("sentence_index", 0),
            output_path=output_path
        )
        return f"批注成功，文件保存在: {out_path}" if success else "批注失败"
    if function_name == "word_reader":
        path = arguments.get("file_path") or arguments.get("pdf_path") or arguments.get("path")
        if not path:
            return "错误：未提供Word文件路径。"
        try:
            safe_path = resolve_workspace_file(path, workspace_scope, allowed_roots=("TEMP", "Result"))
        except WorkspacePathError as e:
            return f"错误：{e}"
        return word_reader(safe_path)
    if function_name == "word_writer":
        path = arguments.get("file_path") or arguments.get("pdf_path") or arguments.get("path")
        if not path:
            return "错误：未提供Word文件路径。"
        try:
            safe_path = resolve_workspace_file(path, workspace_scope, allowed_roots=("TEMP", "Result"))
            output_path = get_result_path(path, workspace_scope)
        except WorkspacePathError as e:
            return f"错误：{e}"
        success = word_writer(safe_path, arguments.get("index"), arguments.get("text"), output_path=output_path)
        return f"批注成功，文件保存在: {output_path}" if success else "批注失败"
    if function_name == "get_company_profile":
        return get_company_profile(arguments.get("company"))
    if function_name == "get_company_registration_info":
        return get_company_registration_info(arguments.get("company"))
    if function_name == "get_contact_info":
        return get_contact_info(arguments.get("company"))
    if function_name == "get_external_investments":
        return get_external_investments(arguments.get("company"))
    if function_name == "get_key_personnel":
        return get_key_personnel(arguments.get("company"))
    if function_name == "get_listing_info":
        return get_listing_info(arguments.get("company"))
    if function_name == "get_shareholder_info":
        return get_shareholder_info(arguments.get("company"))

    return function_name + "工具不存在,请重新检查"


# conv_id 在这里实际承载的是工作区作用域，保持参数名兼容既有调用方。
def use_tools(function_name, arguments, conv_id=None):
    normalized_arguments = _coerce_arguments(function_name, arguments)
    return _dispatch_tool(function_name, normalized_arguments, conv_id)


if __name__ == "__main__":
    match_legal_case(["上班途中车祸工伤案例"], "2020-08-05", "2025-08-05")
    # get_article("民法典", "第七条")
    # match_legal(["啊我死了"])
