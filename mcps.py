#
import json
import deli_client
import os
from dotenv import load_dotenv

load_dotenv(".env")
# 得理的配置
DELI_APPID = os.getenv("DELI_APPID")
DELI_SECRET = os.getenv("DELI_SECRET")
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
                        "description": "用于法律检索的关键语句列表，应提取自用户查询的核心意图，且关键语句数量应小于三个!!!"
                    }
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
                        "description": "用于案例检索的关键语句列表，应提取自用户查询的核心意图，如['案件类型'、'争议焦点']，关键语句数量应小于三个!!!"
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
    }
]
def match_legal(
        keywords: list[str],

):
    """根据查询语义，精准查询对应法规"""
    print("正在调用match_legal\n")
    Client = deli_client.DELIClient(
        appid=DELI_APPID,
        secret=DELI_SECRET
    )
    request_body = Client._build_request_body(
        keywords=keywords,  # 搜索关键词数组
        page_no=1,  # 查询第一页
        page_size=5,  # 每页5条结果
        sort_field="correlation",  # 按相关度排序
        sort_order="desc",  # 降序排列（相关性高的在前）
        # longText="在上下班途中发生非本人主要责任的交通事故是否属于工伤",  # 长文本语义查询
        # caseYearStart=2020,  # 案例起始年份：2020年
        # courtLevelArr=["中级", "高级"]  # 法院层级：中级和高级法院
    )
    # 向法规查询的url发送请求
    result_data = Client._send_request(
        "https://openapi.delilegal.com/api/qa/v3/search/queryListLaw",
        request_body
    )
    # print(json.dumps(result_data, indent=2, ensure_ascii=False))

    #下方是测试用模拟接口数据
    mock_result = {
        "source": result_data["body"]["data"][0]["title"],
        # "article": "第二百六十四条",
        # "content": "盗窃公私财物，数额较大的，或者多次盗窃、入户盗窃、携带凶器盗窃、扒窃的，处三年以下有期徒刑、拘役或者管制..."
    }
    print(json.dumps(mock_result, indent=2, ensure_ascii=False))
    return json.dumps(mock_result, ensure_ascii=False)
def match_legal_case(
        keywords: list[str],
        start_year: str="2020-12-22",
        end_year: str="2025-12-22",
):
    """根据查询语义和时间，精准查询相关的案例"""
    print("正在调用match_legal_case\n")
    Client = deli_client.DELIClient(
        appid=DELI_APPID,
        secret=DELI_SECRET
    )
    request_body = Client._build_request_body(
        keywords=keywords,  # 搜索关键词数组
        caseYearStart=start_year,
        caseYearEnd=end_year,
        page_no=1,  # 查询第一页
        page_size=5,  # 每页5条结果
        sort_field="correlation",  # 按相关度排序
        sort_order="desc",  # 降序排列（相关性高的在前）
        # longText="在上下班途中发生非本人主要责任的交通事故是否属于工伤",  # 长文本语义查询
        # caseYearStart=2020,  # 案例起始年份：2020年
        # courtLevelArr=["中级", "高级"]  # 法院层级：中级和高级法院
    )
    # 向法规查询的url发送请求
    result_data = Client._send_request(
        "https://openapi.delilegal.com/api/qa/v3/search/queryListCase",
        request_body
    )
    # print(json.dumps(result_data, indent=2, ensure_ascii=False))

    # 下方是测试用模拟接口数据
    mock_result = {
        "source": result_data["body"]["data"][0]["title"],
        "judgementDate": result_data["body"]["data"][0]["judgementDate"],
        "content": result_data["body"]["data"][0]["content"],
    }
    print(json.dumps(mock_result, indent=2, ensure_ascii=False))
    return json.dumps(mock_result, ensure_ascii=False)
#在此处处理agent发来的工具请求
def use_tools(function_name,arguments):
    if function_name == "match_legal":
        return match_legal(arguments.get("keywords"))
    if function_name == "match_legal_case":
        return match_legal_case(arguments.get("keywords"))
    return function_name+"工具不存在,请重新检查"
if __name__ == "__main__":
    # match_legal(["深圳市房地产相关的法律规定有哪些？"])
    match_legal_case(["上班途中车祸工伤案例"], "2020-08-05","2025-08-05")
