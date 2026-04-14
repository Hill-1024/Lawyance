from mcp.deli_client import match_legal_case
from mcp.pkulaw_client import get_article, search_article, get_linked_content
from mcp.PDF_processor import pdf_text_reader, pdf_commit_by_sentence
from mcp.word_annotator import word_reader, word_writer
from mcp.qcc_client import get_company_profile,get_listing_info,get_contact_info,get_shareholder_info,get_company_registration_info,get_key_personnel,get_external_investments
import os
import json
import tempfile


def get_result_path(input_path):
    if not input_path:
        return None
    # 统一使用正斜杠并去除首尾空格
    normalized_path = input_path.replace('\\', '/').strip()
    parts = [p for p in normalized_path.split('/') if p]  # 去除空字符串

    # 查找 TEMP 所在的索引
    try:
        if 'TEMP' in parts:
            temp_idx = parts.index('TEMP')
            # 确保 TEMP 之后至少还有 conv_id 和 filename
            if len(parts) > temp_idx + 2:
                conv_id = parts[temp_idx + 1]
                filename = parts[-1]
                base, ext = os.path.splitext(filename)

                # 构造 Result 路径
                result_dir = os.path.join('Result', conv_id)
                os.makedirs(result_dir, exist_ok=True)

                if not base.endswith('_lawver'):
                    base = f"{base}_lawver"
                return os.path.join(result_dir, f"{base}{ext}").replace('\\', '/')
    except Exception:
        pass

    # 如果没找到 TEMP，或者格式不对，回退到原始逻辑但确保在 Result 目录下
    filename = os.path.basename(normalized_path)
    base, ext = os.path.splitext(filename)
    if not base.endswith('_lawver'):
        base = f"{base}_lawver"

    # 尝试寻找可能存在的 conv_id (假设路径中包含类似 UUID 的结构)
    # 如果路径中包含 Result/xxx/，则保留
    if 'Result' in parts:
        res_idx = parts.index('Result')
        if len(parts) > res_idx + 1:
            return normalized_path  # 已经是在 Result 目录下的路径了

    # 默认保存在 Result/misc 目录下，防止前端正则匹配失败
    result_dir = os.path.join('Result', 'misc')
    os.makedirs(result_dir, exist_ok=True)
    return os.path.join(result_dir, f"{base}{ext}").replace('\\', '/')


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


# 在此处处理agent发来的工具请求
def use_tools(function_name, arguments, conv_id=None):
    # 如果 arguments 是字符串，尝试将其转换为字典（针对 ReAct 模式）
    if isinstance(arguments, str):
        try:
            # 尝试解析为 JSON
            arguments = json.loads(arguments)
        except:
            # 如果不是 JSON，则根据函数名构造字典
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
            # 其他工具可能需要更复杂的参数，这里先做基础兼容

    if not isinstance(arguments, dict):
        arguments = {}

    if function_name == "list_workspace_files":
        if not conv_id:
            return "无法获取当前对话ID，无法列出文件。"

        files = []
        # 查找 TEMP 目录
        temp_dir = os.path.join("TEMP", conv_id)
        if os.path.exists(temp_dir):
            for f in os.listdir(temp_dir):
                files.append({"name": f, "path": os.path.join(temp_dir, f).replace('\\', '/')})

        # 查找 Result 目录
        result_dir = os.path.join("Result", conv_id)
        if os.path.exists(result_dir):
            for f in os.listdir(result_dir):
                files.append({"name": f, "path": os.path.join(result_dir, f).replace('\\', '/')})

        if not files:
            return "当前工作区没有任何文件。"

        return json.dumps(files, ensure_ascii=False)

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
        return pdf_text_reader(path)
    if function_name == "pdf_commit_by_sentence":
        path = arguments.get("pdf_path") or arguments.get("file_path") or arguments.get("path")
        if not path:
            return "错误：未提供PDF文件路径。"
        output_path = get_result_path(path)
        success, out_path = pdf_commit_by_sentence(
            path,
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
        return word_reader(path)
    if function_name == "word_writer":
        path = arguments.get("file_path") or arguments.get("pdf_path") or arguments.get("path")
        if not path:
            return "错误：未提供Word文件路径。"
        output_path = get_result_path(path)
        success = word_writer(path, arguments.get("index"), arguments.get("text"), output_path=output_path)
        return f"批注成功，文件保存在: {output_path}" if success else "批注失败"
    return function_name + "工具不存在,请重新检查"


if __name__ == "__main__":
    match_legal_case(["上班途中车祸工伤案例"], "2020-08-05", "2025-08-05")
    # get_article("民法典", "第七条")
    # match_legal(["啊我死了"])
