from mcp.deli_client import match_legal_case, match_legal
from mcp.pkulaw_client import get_article, search_article
from mcp.PDF_processor import pdf_text_reader, pdf_commit_by_sentence
from mcp.word_annotator import word_reader, word_writer
import os

def get_result_path(input_path):
    parts = input_path.replace('\\', '/').split('/')
    if len(parts) >= 3 and parts[0] == 'TEMP':
        conv_id = parts[1]
        filename = parts[-1]
        base, ext = os.path.splitext(filename)
        result_dir = os.path.join('Result', conv_id)
        os.makedirs(result_dir, exist_ok=True)
        return os.path.join(result_dir, f"{base}_gdutlawver{ext}")
    else:
        base, ext = os.path.splitext(input_path)
        return f"{base}_gdutlawver{ext}"

tools = [
    {
        "type": "function",
        "function": {
            "name": "match_legal",
            "description": "查询法律知识库。当需要根据用户语义获取具体的法律条文、量刑标准或处理案件的法律事实依据时，必须调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "用于法律检索的关键语句列表，应提取自用户查询的核心意图，且关键语句数量应小于三个"
                    },

                },
                "required": ["keywords"]
            }
        }
    },
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
                    "number":{
                        "type": "string",
                        "description": "具体的法条号，应提取自用户查询的核心意图，形式如['第九条','第十七条']"
                    }
                },
                "required": ["title","number"]
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
    }
]
#在此处处理agent发来的工具请求
def use_tools(function_name,arguments):
    if function_name == "match_legal":
        return match_legal(arguments.get("keywords"))
    if function_name == "match_legal_case":
        return match_legal_case(arguments.get("keywords"),arguments.get("start_year"),arguments.get("end_year"))
    if function_name == "get_article":
        return get_article(arguments.get("title"),arguments.get("number"))
    if function_name == "search_article":
        return search_article(arguments.get("query"))
    if function_name == "pdf_text_reader":
        return pdf_text_reader(arguments.get("pdf_path"))
    if function_name == "pdf_commit_by_sentence":
        output_path = get_result_path(arguments.get("pdf_path"))
        success, out_path = pdf_commit_by_sentence(
            arguments.get("pdf_path"),
            arguments.get("note_text"),
            arguments.get("page_index", 0),
            arguments.get("sentence_index", 0),
            output_path=output_path
        )
        return f"批注成功，文件保存在: {out_path}" if success else "批注失败"
    if function_name == "word_reader":
        return word_reader(arguments.get("file_path"))
    if function_name == "word_writer":
        output_path = get_result_path(arguments.get("file_path"))
        success = word_writer(arguments.get("file_path"), arguments.get("index"), arguments.get("text"), output_path=output_path)
        return f"批注成功，文件保存在: {output_path}" if success else "批注失败"
    return function_name+"工具不存在,请重新检查"
if __name__ == "__main__":
    match_legal(["深圳市房地产相关的法律规定有哪些？"])
    # match_legal_case(["上班途中车祸工伤案例"], "2020-08-05","2025-08-05")
    # get_article("民法典", "第七条")
    # match_legal(["啊我死了"])
