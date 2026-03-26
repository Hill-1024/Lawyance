import requests
import json
import os
from dotenv import load_dotenv

load_dotenv(".env")
# 1. 准备您的认证信息（请替换为实际值）
DELI_APPID = os.getenv("DELI_APPID") # 示例ID，请使用您自己的
DELI_SECRET = os.getenv("DELI_SECRET")  # 示例Secret，请使用您自己的

class DELIClient:
    def __init__(self, appid = DELI_APPID, secret = DELI_SECRET):
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
            response = requests.post(api_url, headers=self.session.headers, data=json.dumps(request_body))
            response.raise_for_status()  # 检查请求是否成功

            # 5. 解析响应
            result_data = response.json()
            print("API调用成功！")
            # 接下来可以处理 result_data 中的数据...
            return result_data


        except requests.exceptions.RequestException as e:
            print(f"请求发生错误: {e}")
        except json.JSONDecodeError as e:
            print(f"响应JSON解析错误: {e}")

if __name__ == "__main__":
    DELIClient = DELIClient(
        appid = DELI_APPID,
        secret = DELI_SECRET
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