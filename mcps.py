import json

#在此处添加工具描述
tools = [
    {
        "type": "function",
        "function": {
            #工具调用名称(一般直接按函数名写就行)
            "name": "query_legal_db",
            # 工具描述
            "description": "查询法律知识库。当需要获取具体的法律条文、量刑标准或处理案件的法律事实依据时，必须调用此工具。",
            #传递JSON的格式设定
            # TODO 写mcp记得把JSON格式改成自己需要的
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "需要查询的法律关键词，例如:['盗窃罪', '立案标准']"
                    },
                    "law_type": {
                        "type": "string",
                        "enum": ["刑事", "民事", "行政", "综合"],
                        "description": "涉及的法律领域"
                    }
                },
                #要求模型必须包含的返回参数
                "required": ["keywords", "law_type"]
            }
        }
    }
]

def query_legal_db(keywords, law_type):
    # TODO 等待实现
    #下方是测试用模拟接口数据
    mock_result = {
        "source": "《中华人民共和国刑法》",
        "article": "第二百六十四条",
        "content": "盗窃公私财物，数额较大的，或者多次盗窃、入户盗窃、携带凶器盗窃、扒窃的，处三年以下有期徒刑、拘役或者管制..."
    }
    return json.dumps(mock_result, ensure_ascii=False)

#在此处处理agnet发来的工具请求
def use_tools(function_name,arguments):
    if function_name == "query_legal_db":
        return query_legal_db(arguments.get("keywords"),arguments.get("law_type"))
    return function_name+"工具不存在,请重新检查"