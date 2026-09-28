"""
模块描述：企查查企业信息客户端，封装企业画像、登记、股东、高管、联系方式等查询工具。
"""

import io
import json
import logging
import os
import time
import gzip
from typing import Dict, Any, Optional
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
load_dotenv(".env")

logger = logging.getLogger(__name__)
_DEFAULT_ENDPOINT = "https://agent.qcc.com/mcp/company/stream"
_MAX_COMPANY_CHARS = 256
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_DECODED_BYTES = 8 * 1024 * 1024
_MAX_SSE_EVENTS = 128

# 工具配置列表
TOOLS_CONFIG = [
    {
        "name": "get_company_profile",
        "title": "企业简介",
        "description": "查询企业的简介信息，包括企业名称、简介。"
    },
    {
        "name": "get_company_registration_info",
        "title": "企业工商信息",
        "description": "查询企业的核心登记信息，包括法定代表人、注册资本、成立时间等。"
    },
    {
        "name": "get_contact_info",
        "title": "联系方式",
        "description": "查询企业的联系方式信息，包括电话号码、邮箱、企业网站等。"
    },
    {
        "name": "get_external_investments",
        "title": "对外投资",
        "description": "查询企业对外投资信息，包括被投资企业名称、持股比例等。"
    },
    {
        "name": "get_key_personnel",
        "title": "主要人员",
        "description": "查询企业主要管理人员信息，包括姓名、职务等。"
    },
    {
        "name": "get_listing_info",
        "title": "上市信息",
        "description": "查询企业的上市信息，包括股票代码、上市交易所、总市值等。"
    },
    {
        "name": "get_shareholder_info",
        "title": "股东信息",
        "description": "查询企业股东构成信息，包括投资人姓名、持股比例等。"
    }
]
_ALLOWED_TOOL_NAMES = frozenset(item["name"] for item in TOOLS_CONFIG)


class QCCClientError(RuntimeError):
    pass


class QichachaSimpleClient:
    """企查查MCP客户端 - 精简版"""

    def __init__(self):
        """初始化客户端"""
        self.api_key = (os.getenv("QCC_ACCESS_TOKEN") or "").strip()
        if not self.api_key:
            raise QCCClientError("企查查服务尚未配置访问令牌")

        self.endpoint = (os.getenv("QCC_ENDPOINT") or _DEFAULT_ENDPOINT).strip()
        parsed_endpoint = urlparse(self.endpoint)
        if (
            parsed_endpoint.scheme != "https"
            or parsed_endpoint.hostname != "agent.qcc.com"
            or parsed_endpoint.username
            or parsed_endpoint.password
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise QCCClientError("企查查服务地址配置非法")

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip, deflate"
        }

    def _decode_response(self, response_content: bytes) -> str:
        """解码响应内容（处理gzip压缩）"""
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(response_content)) as stream:
                decoded = stream.read(_MAX_DECODED_BYTES + 1)
            if len(decoded) > _MAX_DECODED_BYTES:
                raise QCCClientError("企查查响应解压后过大")
            return decoded.decode("utf-8")
        except gzip.BadGzipFile:
            try:
                return response_content.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise QCCClientError("企查查响应编码异常") from exc

    @staticmethod
    def _read_bounded_response(response: requests.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MAX_RESPONSE_BYTES:
                raise QCCClientError("企查查响应过大")
            chunks.append(chunk)
        return b"".join(chunks)

    def _parse_sse_response(self, sse_content: str) -> list:
        """解析SSE响应格式"""
        events = []
        lines = sse_content.strip().split('\n')
        current_event = {}

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith('event:'):
                current_event['event'] = line[6:].strip()
            elif line.startswith('data:'):
                data_str = line[5:].strip()
                if data_str:
                    try:
                        data = json.loads(data_str)
                        current_event['data'] = data
                    except json.JSONDecodeError:
                        current_event['data'] = {"raw_data": data_str}
                events.append(current_event.copy())
                current_event = {}
                if len(events) >= _MAX_SSE_EVENTS:
                    break

        return events

    def _extract_content_from_response(self, response_data: dict) -> Optional[Dict[str, Any]]:
        """从响应数据中提取content字段"""
        if "error" in response_data:
            raise QCCClientError("企查查服务返回错误")

        # 查找content字段
        if "result" in response_data and isinstance(response_data["result"], dict):
            if "content" in response_data["result"]:
                return response_data["result"]["content"]

        if "content" in response_data:
            return response_data["content"]

        # 如果没有找到content字段，返回整个结果
        return response_data

    def call_tool(self, tool_name: str, search_key: str, **kwargs) -> Dict[str, Any]:
        """
        调用企查查MCP工具

        参数:
            tool_name: 工具名称
            search_key: 搜索关键词（通常是公司名称）
            **kwargs: 其他参数将传递给工具

        返回:
            content字段的JSON数据
        """
        if tool_name not in _ALLOWED_TOOL_NAMES:
            raise QCCClientError("不支持的企查查工具")
        if not isinstance(search_key, str) or not search_key.strip() or len(search_key) > _MAX_COMPANY_CHARS:
            raise QCCClientError("企业名称必须是长度为 1-256 的字符串")

        # 构建参数
        arguments = {"searchKey": search_key.strip()}
        arguments.update(kwargs)

        # 构建请求
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            },
            "id": int(time.time() * 1000)
        }

        # 发送请求
        try:
            response = requests.post(
                self.endpoint,
                headers=self.headers,
                json=payload,
                timeout=30,
                allow_redirects=False,
                stream=True,
            )
            try:
                if response.status_code != 200:
                    raise QCCClientError("企查查服务返回异常状态")
                response_content = self._read_bounded_response(response)
            finally:
                response.close()

            # 解码响应
            decoded_content = self._decode_response(response_content)

            # 解析SSE事件
            events = self._parse_sse_response(decoded_content)

            if not events:
                raise QCCClientError("企查查响应格式异常")

            # 处理第一个事件的data
            if events and "data" in events[0] and isinstance(events[0]["data"], dict):
                data = events[0]["data"]

                # 提取content字段
                content = self._extract_content_from_response(data)

                return content
            else:
                raise QCCClientError("企查查响应格式异常")

        except requests.exceptions.RequestException as exc:
            raise QCCClientError("企查查网络请求失败") from exc


def run_tool(tool_name: str, company: str) -> Dict[str, Any]:
    try:
        # 初始化客户端
        client = QichachaSimpleClient()

        # 调用工具
        result = client.call_tool(tool_name, company)

        return result

    except Exception:
        logger.exception("QCC tool call failed | tool=%s", tool_name)
        return {"error": "企业信息服务调用失败，请稍后重试。"}


def get_company_profile(company: str):
    """查询企业的简介信息，包括企业名称、简介"""
    return run_tool("get_company_profile", company)


def get_company_registration_info(company: str):
    """查询企业的核心登记信息，包括法定代表人、注册资本、成立时间等。"""
    return run_tool("get_company_registration_info", company)


def get_contact_info(company: str):
    """查询企业的联系方式信息，包括电话号码、邮箱、企业网站等。"""
    return run_tool("get_contact_info", company)


def get_external_investments(company: str):
    """查询企业对外投资信息，包括被投资企业名称、持股比例等"""
    return run_tool("get_external_investments", company)


def get_key_personnel(company: str):
    """查询企业主要管理人员信息，包括姓名、职务等"""
    return run_tool("get_key_personnel", company)


def get_listing_info(company: str):
    """查询企业的上市信息，包括股票代码、上市交易所、总市值等"""
    return run_tool("get_listing_info", company)


def get_shareholder_info(company: str):
    """查询企业股东构成信息，包括投资人姓名、持股比例等"""
    return run_tool("get_shareholder_info", company)

def run_single_tool_test(tool_name: str, company: str = "华为技术有限公司") -> Dict[str, Any]:
    """
    运行单个工具测试

    参数:
        tool_name: 工具名称
        company: 公司名称

    返回:
        content字段的JSON数据
    """
    print(f"\n{'=' * 60}")
    print(f"测试工具: {tool_name}")
    print(f"测试公司: {company}")
    print(f"{'=' * 60}")

    try:
        # 初始化客户端
        client = QichachaSimpleClient()

        # 调用工具
        result = client.call_tool(tool_name, company)

        # 打印结果摘要
        if isinstance(result, dict):
            print(f"\n返回数据包含字段: {list(result.keys())[:10]}")  # 只显示前10个字段
        else:
            print(f"\n返回数据类型: {type(result).__name__}")

        return result

    except Exception:
        logger.exception("QCC test tool call failed | tool=%s", tool_name)
        return {"error": "企业信息服务调用失败，请稍后重试。"}


def get_tool_by_name(tool_name: str) -> Optional[Dict[str, Any]]:
    """根据工具名称获取工具配置"""
    for tool in TOOLS_CONFIG:
        if tool["name"] == tool_name:
            return tool
    return None


def list_available_tools() -> list:
    """列出所有可用的工具"""
    return [tool["name"] for tool in TOOLS_CONFIG]


def get_tool_info(tool_name: str) -> Optional[Dict[str, Any]]:
    """获取工具的详细信息"""
    return get_tool_by_name(tool_name)


# 主测试函数
def main():
    """主测试函数"""
    print("企查查MCP工具测试 - 精简版")
    print("=" * 60)

    # 显示可用工具
    print("可用的企查查MCP工具:")
    for i, tool in enumerate(TOOLS_CONFIG, 1):
        print(f"{i}. {tool['name']} - {tool['title']}")

    # 选择要测试的工具
    print("\n选择要测试的工具:")
    print("1. 企业简介 (get_company_profile)")
    print("2. 企业工商信息 (get_company_registration_info)")
    print("3. 联系方式 (get_contact_info)")
    print("4. 对外投资 (get_external_investments)")
    print("5. 主要人员 (get_key_personnel)")
    print("6. 上市信息 (get_listing_info)")
    print("7. 股东信息 (get_shareholder_info)")

    choice = input("\n请输入工具编号 (1-7): ").strip()

    tool_map = {
        "1": "get_company_profile",
        "2": "get_company_registration_info",
        "3": "get_contact_info",
        "4": "get_external_investments",
        "5": "get_key_personnel",
        "6": "get_listing_info",
        "7": "get_shareholder_info"
    }

    if choice in tool_map:
        tool_name = tool_map[choice]
        company = input(f"请输入公司名称 (默认: 华为技术有限公司): ").strip()
        if not company:
            company = "华为技术有限公司"

        # 执行测试
        result = run_single_tool_test(tool_name, company)

        # 打印详细的JSON结果
        print("\n" + "=" * 60)
        print(f"工具 '{tool_name}' 的完整返回结果:")
        print("=" * 60)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        print("❌ 无效的选择")
# 接口测试
if __name__ == "__main__":
    # data = get_company_registration_info("华为技术有限公司")
    # data = get_contact_info("华为技术有限公司")
    # data = get_key_personnel("华为技术有限公司")
    data = get_external_investments("华为技术有限公司")
    # data = get_shareholder_info("华为技术有限公司")
    # data = get_listing_info("华为技术有限公司")
    # data = get_company_profile("华为技术有限公司")
    print(json.dumps(data, indent=2, ensure_ascii=False))

# 使用示例
# if __name__ == "__main__":
#     try:
#         main()
#     except KeyboardInterrupt:
#         print("\n\n程序被用户中断")
#     except Exception as e:
#         print(f"\n程序执行出错: {e}")
#         import traceback
#
#         traceback.print_exc()
