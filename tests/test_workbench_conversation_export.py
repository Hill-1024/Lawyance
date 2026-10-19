"""会话导出 Word 的行为验证：内容、权限、运行态、分支隔离与资源上限。"""

import io
import os
import re
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from workbench.api import router
from workbench.store import Base, engine_for, database_url, transaction, Item, new_id
from services.auth_dependencies import get_current_user


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "LAWVER_DATABASE_URL",
        os.environ.get(
            "LAWVER_TEST_DATABASE_URL", "sqlite:///" + str(tmp_path / "workbench.db")
        ),
    )
    monkeypatch.setenv("LAWVER_WORKBENCH_TESTING", "1")
    monkeypatch.setenv("LAWVER_WORKBENCH_USERS", "alice,bob")
    monkeypatch.setenv("LAWVER_BLOB_DIR", str(tmp_path / "blobs"))
    engine = engine_for(database_url())
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "alice"
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)


def _conversation(client, title, messages):
    conv = client.post(
        "/api/workbench/conversations",
        json={"title": title},
        headers={"Idempotency-Key": new_id()},
    ).json()
    with transaction() as s:
        item = s.get(Item, conv["id"])
        item.data = {**item.data, "messages": messages}
    return conv


def _reopen(response):
    """DOCX 必须能重新打开：返回 (document, 段落全文, 主体 XML)。"""
    from docx import Document

    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.headers["cache-control"] == "no-store"
    doc = Document(io.BytesIO(response.content))
    return doc, "\n".join(p.text for p in doc.paragraphs), doc.element.xml


RICH_ASSISTANT = (
    "## 违约责任分析\n\n"
    "《民法典》第五百七十七条<sup><a href=\"https://flk.npc.gov.cn/art577\">1</a></sup>规定，"
    "**不履行合同义务**应当承担违约责任。\n\n"
    "救济路径：\n\n"
    "1. 继续履行\n"
    "2. 赔偿损失\n"
    "   1. 实际损失\n"
    "   2. 可得利益\n\n"
    "- 证据清单\n"
    "  - 合同原件\n\n"
    "> 法释〔2020〕28 号：违约金过高的举证责任在违约方。\n\n"
    "| 条文 | 要旨 |\n"
    "| --- | --- |\n"
    "| 第五百七十七条 | 违约责任的一般规定 |\n"
    "| 第五百八十四条 | 损失赔偿范围 |\n\n"
    "```python\nprint(577)\n```\n\n"
    "详见 [北大法宝](https://www.pkulaw.com/chl/dc83b04fb8534f1ebdfb.html)。"
)


def _rich_messages():
    return [
        {
            "id": "m-1",
            "role": "user",
            "content": "合同对方逾期付款，我可以主张哪些救济？",
            "created_at": "2026-10-18T02:00:00+00:00",
        },
        {
            "id": "m-2",
            "role": "assistant",
            "content": RICH_ASSISTANT,
            "created_at": "2026-10-18T02:01:00+00:00",
            # trace 是内部历史（system/工具调用），绝不能进导出文档。
            "trace": [
                {"role": "system", "content": "内部系统提示词不该导出"},
                {"role": "tool", "content": "TOOL_RAW_OUTPUT_SECRET"},
                {"role": "assistant", "content": RICH_ASSISTANT},
            ],
        },
    ]


def test_export_preserves_order_content_and_layout(client):
    conv = _conversation(client, "违约救济咨询", _rich_messages())
    response = client.get(f"/api/workbench/conversations/{conv['id']}/export")
    assert response.status_code == 200, response.text
    doc, text, xml = _reopen(response)

    # 顺序与角色标题：用户提问在前、助手回答在后，中文完整保留；
    # 消息时间按本地时区渲染（与导出时间同一口径）。
    expected_user_time = (
        datetime.fromisoformat("2026-10-18T02:00:00+00:00").astimezone().strftime("%Y-%m-%d %H:%M")
    )
    expected_assistant_time = (
        datetime.fromisoformat("2026-10-18T02:01:00+00:00").astimezone().strftime("%Y-%m-%d %H:%M")
    )
    user_at = text.index("合同对方逾期付款，我可以主张哪些救济？")
    assistant_at = text.index("不履行合同义务")
    assert text.index(f"用户 · {expected_user_time}") < user_at
    assert user_at < assistant_at
    assert f"Lawver 助手 · {expected_assistant_time}" in text

    # 结构化排版：标题、有序/无序列表、引用块、代码块文本都在。
    assert "违约责任分析" in text  # 标题（Heading 2）
    assert "1. 继续履行" in text and "2. 赔偿损失" in text
    assert "1. 实际损失" in text and "2. 可得利益" in text  # 嵌套有序号从 1 重新计
    assert "证据清单" in text and "合同原件" in text
    assert "法释〔2020〕28 号" in text
    assert "print(577)" in text

    # GFM 表格：重新打开后仍是真表格，表头表体齐全。
    assert len(doc.tables) == 1
    cells = [c.text for row in doc.tables[0].rows for c in row.cells]
    assert "第五百七十七条" in cells and "损失赔偿范围" in cells

    # 粗体与上标角标：XML 里能看到对应属性；原始 HTML 标签不落正文。
    assert "<w:b/>" in xml
    assert xml.count('w:val="superscript"') >= 1
    assert "<sup>" not in text and "</a>" not in text

    # 链接：正文链接与角标链接都成为真实超链接关系。
    external = [str(r.target_ref) for r in doc.part.rels.values() if r.is_external]
    assert any("flk.npc.gov.cn/art577" in url for url in external)
    assert any("pkulaw.com" in url for url in external)

    # 导出时间明确到时区（正负偏移都接受，跟随运行机器）。
    assert "导出时间：" in text
    assert re.search(r"UTC[+-]\d{2}:\d{2}", text)


def test_internal_messages_and_tool_events_never_exported(client):
    messages = [
        {"id": "m-0", "role": "system", "content": "系统提示词不该出现"},
        {"id": "m-1", "role": "developer", "content": "开发者消息不该出现"},
        {"id": "m-2", "role": "user", "content": "用户问题应保留"},
        {"id": "m-3", "role": "tool", "content": "TOOL_EVENT_NOT_EXPORTED"},
        {
            "id": "m-4",
            "role": "assistant",
            "content": "正式回答应保留",
            "trace": [{"role": "system", "content": "TRACE_SECRET_NOT_EXPORTED"}],
        },
        {"id": "m-5", "role": "user", "content": 12345},  # 非字符串内容：跳过
    ]
    conv = _conversation(client, "混合会话", messages)
    doc, text, _ = _reopen(client.get(f"/api/workbench/conversations/{conv['id']}/export"))
    assert "用户问题应保留" in text and "正式回答应保留" in text
    for banned in ("系统提示词不该出现", "开发者消息不该出现", "TOOL_EVENT_NOT_EXPORTED", "TRACE_SECRET_NOT_EXPORTED"):
        assert banned not in text


def test_export_access_control(client):
    conv = _conversation(client, "权限会话", _rich_messages())
    path = f"/api/workbench/conversations/{conv['id']}/export"
    # 匿名（无 token）：401。
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = get_current_user  # 撤销测试替身
    with TestClient(app) as anonymous:
        assert anonymous.get(path).status_code == 401
    # 他人会话：与既有路由同一语义（404，不泄露存在性）。
    client.app.dependency_overrides[get_current_user] = lambda: "bob"
    assert client.get(path).status_code == 404
    client.app.dependency_overrides[get_current_user] = lambda: "alice"
    # 回收站里的会话同样 404。
    assert client.delete(f"/api/workbench/conversations/{conv['id']}").status_code == 200
    assert client.get(path).status_code == 404


def test_export_refused_while_running_and_when_empty(client):
    # 空会话：明确提示，不产出空文档。
    empty = client.post(
        "/api/workbench/conversations",
        json={"title": "空会话"},
        headers={"Idempotency-Key": new_id()},
    ).json()
    refused = client.get(f"/api/workbench/conversations/{empty['id']}/export")
    assert refused.status_code == 422
    assert "还没有可导出的消息" in refused.json()["detail"]

    # 运行中：409 明确冲突，不静默导出半截回答。
    conv = _conversation(client, "运行会话", _rich_messages())
    started = client.post(
        "/api/workbench/runs",
        json={"conversation_id": conv["id"], "message": "继续分析", "references": []},
        headers={"Idempotency-Key": new_id()},
    )
    assert started.status_code == 200
    assert (
        client.get(f"/api/workbench/conversations/{conv['id']}/export").status_code
        == 409
    )


def test_export_branch_isolation(client):
    parent = _conversation(client, "原会话", [
        {"id": "m-1", "role": "user", "content": "分支前的问题"},
        {"id": "m-2", "role": "assistant", "content": "分支前的回答", "trace": []},
        {"id": "m-3", "role": "user", "content": "分支后父会话独有的问题"},
        {"id": "m-4", "role": "assistant", "content": "分支后父会话独有的回答"},
    ])
    branch = client.post(
        f"/api/workbench/conversations/{parent['id']}/branch",
        json={"message_id": "m-2", "title": "分支会话"},
        headers={"Idempotency-Key": new_id()},
    ).json()
    # 分支继续长出自己的回答。
    with transaction() as s:
        item = s.get(Item, branch["id"])
        item.data = {
            **item.data,
            "messages": [
                *item.data["messages"],
                {"id": "b-1", "role": "user", "content": "分支上的追问"},
                {"id": "b-2", "role": "assistant", "content": "分支上的回答"},
            ],
        }
    _, branch_text, _ = _reopen(
        client.get(f"/api/workbench/conversations/{branch['id']}/export")
    )
    assert "分支前的问题" in branch_text and "分支前的回答" in branch_text
    assert "分支上的追问" in branch_text and "分支上的回答" in branch_text
    # 兄弟分支与父会话后续内容绝不混入。
    assert "分支后父会话独有的问题" not in branch_text
    assert "分支后父会话独有的回答" not in branch_text
    # 父会话导出仍然完整持有自己的四条。
    _, parent_text, _ = _reopen(
        client.get(f"/api/workbench/conversations/{parent['id']}/export")
    )
    assert "分支后父会话独有的回答" in parent_text
    assert "分支上的追问" not in parent_text


def test_export_is_read_only(client):
    conv = _conversation(client, "只读验证", _rich_messages())
    before = client.get(f"/api/workbench/conversations/{conv['id']}").json()
    response = client.get(f"/api/workbench/conversations/{conv['id']}/export")
    assert response.status_code == 200
    after = client.get(f"/api/workbench/conversations/{conv['id']}").json()
    # revision 与消息不变；导出不产生新 run、不触发模型任务。
    assert before["revision"] == after["revision"]
    assert before["data"]["messages"] == after["data"]["messages"]
    with transaction() as s:
        runs = s.scalars(select(Item).where(Item.kind == "run")).all()
        assert runs == []


def test_export_resource_limits(client, monkeypatch):
    from workbench import conversation_export

    conv = _conversation(client, "超限会话", _rich_messages())
    monkeypatch.setattr(conversation_export, "MAX_EXPORT_MESSAGES", 1)
    too_many = client.get(f"/api/workbench/conversations/{conv['id']}/export")
    assert too_many.status_code == 422
    assert "超过" in too_many.json()["detail"]

    monkeypatch.setattr(conversation_export, "MAX_EXPORT_MESSAGES", 2000)
    monkeypatch.setattr(conversation_export, "MAX_EXPORT_CHARS", 10)
    too_large = client.get(f"/api/workbench/conversations/{conv['id']}/export")
    assert too_large.status_code == 422
    assert "总量过大" in too_large.json()["detail"]


def test_export_headers_use_safe_chinese_filename(client):
    conv = _conversation(client, '报告/2026:第"四"季度', _rich_messages())
    response = client.get(f"/api/workbench/conversations/{conv['id']}/export")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''" in disposition
    # 路径字符与引号不得原样进入响应头（quote 会转义）。
    assert "/" not in disposition.split("UTF-8''")[-1]
    assert '"' not in disposition.split("UTF-8''")[-1]
    assert "\r" not in disposition and "\n" not in disposition
