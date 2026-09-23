"""
模块描述：得理案例检索客户端，封装认证请求、异常处理和案例匹配工具。
"""

import requests
import json
import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(".env")

# 响应体读取上限：得理是受信上游，但仍按其余外部客户端同一标准限长，防止异常响应耗尽内存。
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class DELINotConfiguredError(RuntimeError):
    """DELI_APPID / DELI_SECRET 尚未配置（环境变量或管理后台）。"""


def _load_credentials() -> tuple[str, str]:
    """调用期读取凭据：既不因缺配置阻断整个后端启动，也让管理后台热更新即时生效。"""
    appid = (os.getenv("DELI_APPID") or "").strip()
    secret = (os.getenv("DELI_SECRET") or "").strip()
    if not appid or not secret:
        raise DELINotConfiguredError("得理法搜尚未配置 appid/secret")
    return appid, secret


class DELIClient:
    def __init__(self, appid: str | None = None, secret: str | None = None):
        if appid is None or secret is None:
            appid, secret = _load_credentials()
        self.appid = appid
        self.secret = secret
        self.session = requests.Session()
        # 初始化得理默认请求头
        self.session.headers.update({
            "Content-Type": "application/json",
            "appid": self.appid,
            "secret": self.secret
        })

    def _build_request_body(
            self,
            keywords: list[str],
            page_no: int = 1,
            page_size: int = 10,
            sort_field: str = "correlation",
            sort_order: str = "desc",
            **extra_conditions
    ) -> dict[str, any]:
        """
        构建请求体

        基于可运行的payload结构：
        {
            "pageNo": 1,
            "pageSize": 5,
            "sortField": "correlation",
            "sortOrder": "desc",
            "condition": {
                "keywordArr": ["工伤保险"]
            }
        }

        :param keywords: 关键词列表，如 ["工伤保险", "认定"]
        :param page_no: 要查询的页码，从1开始
        :param page_size: 每一页返回的案例数量
        :param sort_field: 结果排序的字段
        :param sort_order: 排序顺序，"desc"是降序，即相关性最高的排在最前面
        :param extra_conditions: 额外的搜索条件，会合并到condition对象中
        :return: 构建好的请求体字典
        """
        # 基础请求体结构
        request_body = {
            "pageNo": page_no,
            "pageSize": page_size,
            "sortField": sort_field,
            "sortOrder": sort_order,
            "condition": {
                "keywordArr": keywords
            }
        }

        # 将额外条件合并到condition中
        if extra_conditions:
            request_body["condition"].update(extra_conditions)

        return request_body
    def _send_request(self, api_url, request_body):
        """
        将POST请求发送给服务端
        :param api_url:与工具对应的url
        :param request_body:请求体
        :return: 请求结果
        """
        try:
            response = requests.post(
                api_url,
                headers=self.session.headers,
                data=json.dumps(request_body),
                timeout=30,
                stream=True,
            )
            try:
                response.raise_for_status()  # 检查请求是否成功
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        logger.warning("得理案例检索响应超过 %d 字节，已中止读取", _MAX_RESPONSE_BYTES)
                        return {"success": False, "message": "案例检索响应过大"}
                    chunks.append(chunk)
            finally:
                response.close()

            # 5. 解析响应
            result_data = json.loads(b"".join(chunks).decode(response.encoding or "utf-8", errors="replace"))
            logger.debug("得理案例检索 API 调用成功")
            # 接下来可以处理 result_data 中的数据...
            return result_data


        except requests.exceptions.RequestException as e:
            logger.warning("得理案例检索网络请求失败: %s", e)
            return {"success": False, "message": f"案例检索网络请求失败: {e}"}
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("得理案例检索响应解析失败: %s", e)
            return {"success": False, "message": f"案例检索响应解析失败: {e}"}

def build_client():
    appid, secret = _load_credentials()
    return DELIClient(appid=appid, secret=secret)

def match_legal_case(
        keywords: list[str],
        start_year: str="2020-12-22",
        end_year: str="2025-12-22",
):
    """根据查询语义和时间，精准查询相关的案例"""
    logger.debug("调用工具 match_legal_case")
    try:
        client = build_client()
    except DELINotConfiguredError:
        return {
            "success": False,
            "message": "案例检索服务未配置：请先在管理后台或环境变量中设置 DELI_APPID/DELI_SECRET。",
        }
    request_body = client._build_request_body(
        keywords=keywords,  # 搜索关键词数组
        caseYearStart=start_year,
        caseYearEnd=end_year,
        page_no=1,  # 查询第一页
        page_size=8,  # 每页5条结果
        sort_field="correlation",  # 按相关度排序
        sort_order="desc",  # 降序排列（相关性高的在前）
    )
    # 向法规查询的url发送请求
    result_data = client._send_request(
        "https://openapi.delilegal.com/api/qa/v3/search/queryListCase",
        request_body
    )
    # print(json.dumps(result_data, indent=2, ensure_ascii=False))

    if not isinstance(result_data, dict) or not isinstance(result_data.get("body"), dict):
        return {
            "success": False,
            "message": result_data.get("message", "案例检索服务返回异常") if isinstance(result_data, dict) else "案例检索服务返回异常"
        }

    body = result_data.get("body") or {}
    raw_items = body.get("data")
    items = raw_items if isinstance(raw_items, list) else []
    try:
        total_count = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        total_count = 0

    if total_count == 0 or not items:
        return {
            "success": False,
            "message": "没有找到匹配的案例，请修改关键词"
        }

    count = min(total_count, len(items), 8)
    # 下方是返回的数据
    result = []
    for item in items[:count]:
        if not isinstance(item, dict):
            continue
        result.append({
            "source": item.get("title", ""),
            "judgementDate": item.get("judgementDate", ""),
            "content": item.get("content", ""),
        })
    mock_result = {
        "success": True,
        "data": result,
    }
    return json.dumps(mock_result, ensure_ascii=False)
if __name__ == "__main__":
    # 以下代码用于测试连接，现在暂时用不了，需测试工具要运行mcps.py
    DELIClient = DELIClient(
        appid=os.getenv("DELI_APPID"),
        secret=os.getenv("DELI_SECRET")
    )
    # 请求体构建测试
    request_body = DELIClient._build_request_body(
        keywords=["工伤保险"],  # 搜索关键词数组
        page_no=1,  # 查询第一页
        page_size=5,  # 每页5条结果
        sort_field="correlation",  # 按相关度排序
        sort_order="desc",  # 降序排列（相关性高的在前）
        # longText="在上下班途中发生非本人主要责任的交通事故是否属于工伤",  # 长文本语义查询
        # caseYearStart=2020,  # 案例起始年份：2020年
        # courtLevelArr=["中级", "高级"]  # 法院层级：中级和高级法院
    )
    import json
    print(json.dumps(request_body, indent=2, ensure_ascii=False))
    # 请求包发送测试
    result_data = DELIClient._send_request(
        "https://openapi.delilegal.com/api/qa/v3/search/queryListCase",
        request_body
    )
    print(json.dumps(result_data, indent=2, ensure_ascii=False))  # 美化打印JSON
