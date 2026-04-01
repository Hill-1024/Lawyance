import os
from dotenv import load_dotenv
load_dotenv(".env")

PKU_ACCESS_TOKEN = os.getenv("PKU_ACCESS_TOKEN")
# 异常检测
if not PKU_ACCESS_TOKEN:
    raise ValueError("PKU_ACCESS_TOKEN is not set in the environment variables.")

import sys

import json
import requests
from typing import Dict, Any, Optional

def parse_sse_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    解析SSE格式的响应，提取JSON数据

    Args:
        response_text: SSE格式的响应文本

    Returns:
        解析后的JSON数据，如果解析失败则返回None
    """
    if not response_text:
        return None

    lines = response_text.strip().split('\n')
    json_data = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 处理SSE格式
        if line.startswith('data: '):
            json_str = line[6:]  # 去掉"data: "前缀
            if json_str:  # 确保不是空数据
                try:
                    json_data = json.loads(json_str)
                    break  # 找到第一个有效数据就返回
                except json.JSONDecodeError:
                    # 可能是分行的JSON，继续处理
                    continue

    # 如果没有找到SSE格式的数据，尝试直接解析
    if json_data is None:
        try:
            json_data = json.loads(response_text)
        except json.JSONDecodeError:
            return None

    return json_data



class PkulawMCPClient:
    """
    北大法宝的每个服务url有一个tool列表
    """
    def __init__(self, service_url, access_token):
        """
        初始化MCP客户端
        :param service_url: 从北大法宝控制台获取的完整服务URL
        :param access_token: 从北大法宝控制台获取的Access Token
        """
        if not service_url or not service_url.startswith("http"):
            print(f"错误: 无效的service_url: '{service_url}'。请从北大法宝控制台获取正确的URL。", file=sys.stderr)
            sys.exit(1)

        self.service_url = service_url
        self.access_token = access_token
        # 正确的请求头，包含Accept
        self.headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream',
            'Authorization': f'Bearer {access_token}'
        }
        self.request_counter = 0

    def _make_request(self, payload):
        """发送请求并返回原始响应对象，便于调试"""
        self.request_counter += 1
        payload["id"] = self.request_counter  # 使用递增的ID

        # print(f"\n=== 发送请求 ===")
        # print(f"URL: {self.service_url}")
        # print(f"Headers: { {k: v for k, v in self.headers.items() if k != 'Authorization'} }")
        # print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")

        try:
            # 添加超时设置，避免长时间等待
            response = requests.post(
                self.service_url,
                headers=self.headers,
                json=payload,
                timeout=30
            )

            print(f"=== 收到响应 ===")
            print(f"状态码: {response.status_code}")
            # print(f"响应头: {dict(response.headers)}")

            raw_text = response.text
            # print(f"原始响应 (前1000字符):\n{raw_text[:1000]}")

            # 解析SSE响应
            parsed_data = parse_sse_response(raw_text)

            if parsed_data is None:
                return {
                    "error": "无法解析SSE响应",
                    "raw_response": raw_text[:500]
                }

            # 创建一个包装对象，使其能像普通响应一样工作
            class ParsedResponse:
                def __init__(self, data, status_code, headers):
                    self._data = data
                    self.status_code = status_code
                    self.headers = headers
                    self.text = json.dumps(data, ensure_ascii=False)

                def json(self):
                    return self._data

            return ParsedResponse(parsed_data, response.status_code, response.headers)

        except requests.exceptions.Timeout:
            print("错误: 请求超时 (30秒)。请检查网络或服务状态。", file=sys.stderr)
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"错误: 连接失败 - {e}", file=sys.stderr)
            return None
        except requests.exceptions.RequestException as e:
            print(f"错误: 请求异常 - {e}", file=sys.stderr)
            return None

    def list_tools(self):
        """获取可用工具列表"""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list"
        }

        response = self._make_request(payload)
        if not response:
            return {"error": "请求发送失败"}

        # 检查HTTP状态码
        if response.status_code != 200:
            return {
                "error": f"HTTP错误 {response.status_code}",
                "status_code": response.status_code,
                "text": response.text[:500]
            }

        # 尝试解析JSON
        try:
            return response.json()
        except json.JSONDecodeError as e:
            return {
                "error": f"响应不是有效的JSON: {e}",
                "raw_response_preview": response.text[:500]
            }

    def call_tool(self, tool_name, arguments):
        """调用MCP工具"""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        response = self._make_request(payload)
        if not response:
            return {"error": "请求发送失败"}

        if response.status_code != 200:
            return {
                "error": f"HTTP错误 {response.status_code}",
                "status_code": response.status_code,
                "text": response.text[:500]
            }

        try:
            return response.json()
        except json.JSONDecodeError as e:
            return {
                "error": f"响应不是有效的JSON: {e}",
                "raw_response_preview": response.text[:500]
            }
def get_article(title:str, number:str):
    """根据法律名称和条号，精确获取指定法条的完整内容"""
    service_url = "https://apim-gateway.pkulaw.com/mcp-law-search-service"
    print("正在调用PKU:get_article")
    client = PkulawMCPClient(service_url, PKU_ACCESS_TOKEN)
    # 发送请求寻找tools列表
    tools_result = client.list_tools()
    article_result = client.call_tool("get_article", {
        "title": title,
        "number": number
    })
    mock_result = {
        "success": True,
        "title": article_result["result"]["structuredContent"]["title"],
        "content": article_result["result"]["structuredContent"]["article"],
        "url": article_result["result"]["structuredContent"]["url"],

    }
    if mock_result["title"] == "":
        return {
            "success": False,
            "message": "未找到匹配的条，请修改查询关键词"
        }

    print(f"法条内容: {json.dumps(mock_result, ensure_ascii=False)}")
    return json.dumps(mock_result, ensure_ascii=False)
def search_article(text:str):
    """根据语义检索相关的法律条文，适用于不确定具体法条、需要查找相关规定的场景"""
    print("正在调用PKU:search_article")
    service_url = "https://apim-gateway.pkulaw.com/mcp-law-search-service"
    client = PkulawMCPClient(service_url, PKU_ACCESS_TOKEN)
    # 发送请求寻找tools列表
    tools_result = client.list_tools()

    search_result = client.call_tool("search_article", {
        "text": text
    })
    result = search_result["result"]["content"]
    if not result:
        print("未检索到相关法条")
        result = {
            "success": False,
            "message": "未检索到相关法条,请调整输入的描述"
        }
        return json.dumps(result, ensure_ascii=False)

    mock_result = {
        "success": True,
        "result": result,
    }
    # print(f"法条内容: {json.dumps(mock_result, ensure_ascii=False)}")
    return json.dumps(mock_result, ensure_ascii=False)
# 幻觉修正函数能正常发包并返回包，但是返回内容为空，不知道原因，暂时没有写在mcps中
def adjust_provisions(title:str, article_number:str, text:str):
    """分析大模型在回答用户问题时引用的具体法条和司法解释条款，返回更加权威、准确的法律条文以及司法解释的内容及原文引用地址"""
    print("正在调用PKU:adjust_provisions")
    service_url = "https://apim-gateway.pkulaw.com/pku_citation_validator"
    client = PkulawMCPClient(service_url, PKU_ACCESS_TOKEN)
    user_law = [
        {
            "title":title,
            "article_number": article_number
        }
    ]
    answer_law = [
        {
            "title": title,
            "article_number": article_number,
            "text": text,
        }
    ]
    param = {
        "user_law": user_law,
        "answer_law": answer_law,
    }
    print(param)
    # 发送请求寻找tools列表
    tools_result = client.list_tools()

    adjust_result = client.call_tool("adjust_provisions", {
        "param": param
    })
    mock_result = {
        "success": True,
        "title": adjust_result["result"]["content"],
    }
    print(json.dumps(mock_result, ensure_ascii=False))
    return json.dumps(adjust_result, ensure_ascii=False)
def get_linked_content(message:str):
    """根据输入的语义返回相关信息的超链接"""
    service_url = "https://apim-gateway.pkulaw.com/add-doc-link"
    print("正在调用PKU:get_linked_content")
    client = PkulawMCPClient(service_url, PKU_ACCESS_TOKEN)
    # 发送请求寻找tools列表
    tools_result = client.list_tools()
    link_result = client.call_tool("get_linked_content", {
        "message": message,
    })
    # print(json.dumps(link_result, ensure_ascii=False))
    mock_result = {
        "success": True,
        "text": link_result["result"]["content"],

    }
    print(f"法条内容: {json.dumps(mock_result, ensure_ascii=False)}")
    return json.dumps(mock_result, ensure_ascii=False)

def main():
    """
    主函数，用于测试连接
    """
    SERVICE_URL = "https://apim-gateway.pkulaw.com/mcp-law-search-service"  # 法条查询服务的URL

    # 1. 初始化客户端
    print("正在初始化MCP客户端...")
    client = PkulawMCPClient(SERVICE_URL, PKU_ACCESS_TOKEN)

    # 2. 首先尝试获取工具列表
    print("\n" + "=" * 50)
    print("测试1: 获取工具列表")
    print("=" * 50)
    tools_result = client.list_tools()

    # 测试get_article
    article_result = client.call_tool("get_article", {
        "title": "民事诉讼法",
        "number": "第七条"
    })
    print(f"法条内容: {article_result}")

    # 测试search_article
    search_result = client.call_tool("search_article", {
        "text": "危险货物的定义"
    })
    print(f"检索结果: {search_result}")

    # 测试工具函数
    print("\n" + "=" * 50)
    print(search_article("危险货物的定义"))
    print(get_article("民事诉讼法","第七条"))


if __name__ == "__main__":
    main()