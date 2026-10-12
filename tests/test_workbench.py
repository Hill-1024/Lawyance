import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest import mock
from types import SimpleNamespace
from sqlalchemy import select

from workbench.api import router
from workbench.store import Base, engine_for, database_url, transaction, Item, new_id
from workbench.documents import native
from services.auth_dependencies import get_current_user


@pytest.fixture(autouse=True)
def _reset_suggestions():
    from workbench import suggestions

    suggestions.reset_cache()
    yield


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
    from workbench.migration import router as migrations
    from workbench.backup import router as backups

    app = FastAPI()
    app.include_router(migrations)
    app.include_router(backups)
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "alice"
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)


def project(c):
    # 幂等键方向 A 之后创建类 POST 一律强制带键；用例间随机键避免 receipt 去重串台。
    return c.post(
        "/api/workbench/projects",
        json={"title": "测试项目"},
        headers={"Idempotency-Key": new_id()},
    ).json()


def document(c, p):
    return c.post(
        "/api/workbench/documents",
        json={
            "title": "合同",
            "project_id": p["id"],
            "content": native("付款期限为三十日。\n双方应保密。"),
        },
        headers={"Idempotency-Key": new_id()},
    ).json()


def test_version_conflict_and_restore(client):
    p = project(client)
    d = document(client, p)
    r = client.put(
        "/api/workbench/documents/" + d["id"] + "/content",
        json={"expected_revision": 1, "content": native("付款期限为十五日。")},
    )
    assert r.status_code == 200
    assert r.json()["revision"] == 2
    r = client.put(
        "/api/workbench/documents/" + d["id"] + "/content",
        json={"expected_revision": 1, "content": native("不应覆盖")},
    )
    assert r.status_code == 409
    r = client.post(
        "/api/workbench/documents/" + d["id"] + "/restore-version",
        json={"expected_revision": 2, "revision": 1},
        headers={"Idempotency-Key": "restore-version-1"},
    )
    assert r.status_code == 200
    assert r.json()["revision"] == 3
    assert "三十日" in str(r.json()["data"]["content"])


def test_owner_project_context_and_idempotency(client):
    p = project(client)
    d = document(client, p)
    q = project(client)
    c = client.post(
        "/api/workbench/conversations",
        json={"title": "咨询", "project_id": p["id"]},
        headers={"Idempotency-Key": "conv-1"},
    ).json()
    body = {
        "conversation_id": c["id"],
        "message": "审查",
        "references": [{"kind": "document", "id": d["id"], "revision": 1}],
    }
    r = client.post("/api/workbench/runs", json=body, headers={"Idempotency-Key": "run-1"})
    assert r.status_code == 200, r.text
    assert (
        client.post(
            "/api/workbench/runs", json=body, headers={"Idempotency-Key": "run-1"}
        ).json()["id"]
        == r.json()["id"]
    )
    assert (
        client.post(
            "/api/workbench/runs",
            json={**body, "message": "其他"},
            headers={"Idempotency-Key": "run-1"},
        ).status_code
        == 409
    )
    client.app.dependency_overrides[get_current_user] = lambda: "bob"
    assert client.get("/api/workbench/documents/" + d["id"]).status_code == 404
    client.app.dependency_overrides[get_current_user] = lambda: "alice"
    c2 = client.post(
        "/api/workbench/conversations",
        json={"title": "其他", "project_id": q["id"]},
        headers={"Idempotency-Key": "conv-2"},
    ).json()
    assert (
        client.post(
            "/api/workbench/runs",
            json={**body, "conversation_id": c2["id"]},
            headers={"Idempotency-Key": "cross"},
        ).status_code
        == 403
    )


def test_partial_review_and_duplicate_accept(client):
    p = project(client)
    d = document(client, p)
    ids = []
    with transaction() as s:
        for before, after in [("三十日", "十五日"), ("双方应保密", "双方应持续保密")]:
            item = Item(
                id=new_id(),
                owner="alice",
                kind="proposal",
                parent_id=d["id"],
                project_id=p["id"],
                title="审查",
                data={
                    "before": before,
                    "after": after,
                    "base_revision": 1,
                    "status": "pending",
                },
            )
            s.add(item)
            ids.append(item.id)
    body = {"expected_revision": 1, "action": "accept"}
    r = client.post(
        "/api/workbench/change-proposals/" + ids[0] + "/decision",
        json=body,
        headers={"Idempotency-Key": "accept-1"},
    )
    assert r.status_code == 200, r.text
    assert (
        client.post(
            "/api/workbench/change-proposals/" + ids[0] + "/decision",
            json=body,
            headers={"Idempotency-Key": "accept-1"},
        ).json()
        == r.json()
    )
    r = client.post(
        "/api/workbench/change-proposals/" + ids[1] + "/decision",
        json={"expected_revision": 2, "action": "accept"},
        headers={"Idempotency-Key": "accept-2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["document"]["revision"] == 3


def test_delete_conversation_retains_project_file(client):
    p = project(client)
    d = document(client, p)
    c = client.post(
        "/api/workbench/conversations",
        json={"title": "咨询", "project_id": p["id"]},
        headers={"Idempotency-Key": new_id()},
    ).json()
    assert client.delete("/api/workbench/conversations/" + c["id"]).status_code == 200
    assert client.get("/api/workbench/documents/" + d["id"]).status_code == 200
    assert client.delete("/api/workbench/projects/" + p["id"]).status_code == 200
    assert client.get("/api/workbench/documents/" + d["id"]).status_code == 404
    assert (
        client.post(
            "/api/workbench/trash/" + p["id"] + "/restore",
            headers={"Idempotency-Key": new_id()},
        ).status_code
        == 200
    )
    assert client.get("/api/workbench/documents/" + d["id"]).status_code == 200


def test_upload_and_native_export(client):
    p = project(client)
    r = client.post(
        "/api/workbench/documents/upload",
        data={"project_id": p["id"]},
        files={"file": ("材料.txt", "测试材料".encode(), "text/plain")},
        headers={"Idempotency-Key": "upload-1"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert "blob_key" not in d["data"]
    assert (
        client.get("/api/workbench/documents/" + d["id"] + "/blob").content
        == "测试材料".encode()
    )
    copy = client.post(
        "/api/workbench/documents/" + d["id"] + "/editable-copy",
        headers={"Idempotency-Key": "editable-1"},
    ).json()
    assert (
        client.get("/api/workbench/documents/" + copy["id"] + "/export").content[:2] == b"PK"
    )


def test_plugin_rejects_non_https_and_private_dns(client):
    assert (
        client.post(
            "/api/workbench/connectors",
            json={"title": "不安全", "url": "http://localhost/mcp"},
            headers={"Idempotency-Key": new_id()},
        ).status_code
        == 422
    )
    from workbench.connectors import PublicTransport
    import asyncio, httpx

    async def attempt():
        async with httpx.AsyncClient(transport=PublicTransport()) as c:
            with pytest.raises(ValueError):
                await c.get("https://127.0.0.1/mcp")

    asyncio.run(attempt())


def test_readonly_mode_preserves_reads(client, monkeypatch):
    p = project(client)
    d = document(client, p)
    monkeypatch.setenv("LAWVER_WORKBENCH_READ_ONLY", "1")
    assert client.get("/api/workbench/documents/" + d["id"]).status_code == 200
    assert client.get("/api/workbench/documents/" + d["id"] + "/export").status_code == 200
    assert (
        client.put(
            "/api/workbench/documents/" + d["id"] + "/content",
            json={"expected_revision": 1, "content": native("禁止写入")},
        ).status_code
        == 503
    )


def test_stale_proposal_does_not_overwrite(client):
    p = project(client)
    d = document(client, p)
    with transaction() as s:
        item = Item(
            id=new_id(),
            owner="alice",
            kind="proposal",
            parent_id=d["id"],
            project_id=p["id"],
            title="审查",
            data={
                "before": "三十日",
                "after": "十五日",
                "base_revision": 1,
                "status": "pending",
            },
        )
        s.add(item)
        identifier = item.id
    client.put(
        "/api/workbench/documents/" + d["id"] + "/content",
        json={
            "expected_revision": 1,
            "content": native("付款期限为三十日。\n另一设备追加内容。"),
        },
    )
    r = client.post(
        "/api/workbench/change-proposals/" + identifier + "/decision",
        json={"expected_revision": 2, "action": "accept"},
        headers={"Idempotency-Key": "stale"},
    )
    assert r.status_code == 409
    assert "另一设备" in str(client.get("/api/workbench/documents/" + d["id"]).json())


def test_migration_attachment_retry_and_backup(client):
    payload = {
        "source_id": "test",
        "conversations": [
            {
                "id": "old",
                "title": "旧会话",
                "messages": [{"id": "m", "role": "user", "content": "材料"}],
            }
        ],
        "files": [
            {
                "conversation_id": "old",
                "name": "材料.txt",
                "path": "TEMP/old/材料.txt",
                "available": True,
            }
        ],
    }
    r = client.post(
        "/api/workbench/migrations", json=payload, headers={"Idempotency-Key": "migration"}
    )
    assert r.status_code == 200, r.text
    migration = r.json()
    path = "/api/workbench/migrations/" + migration["id"] + "/files"
    data = {"conversation_id": "old", "original_path": "TEMP/old/材料.txt"}
    files = {"file": ("材料.txt", "虚构材料".encode(), "text/plain")}
    first = client.post(path, data=data, files=files)
    second = client.post(path, data=data, files=files)
    assert first.status_code == 200, first.text
    assert first.json()["id"] == second.json()["id"]
    backup = client.get("/api/workbench/backup")
    assert backup.status_code == 200, backup.text[:200]
    r = client.post(
        "/api/workbench/backup",
        files={"file": ("backup.zip", backup.content, "application/zip")},
        headers={"Idempotency-Key": "restore"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["restored"] >= 3


def test_project_optional_description_roundtrip(client):
    plain = project(client)
    assert plain['data']['desc'] == ''
    response = client.post('/api/workbench/projects', json={'title': '合同审查', 'desc': '  梳理付款条款\n核对交付期限  '}, headers={'Idempotency-Key': new_id()})
    assert response.status_code == 200
    saved = response.json()
    detail = client.get('/api/workbench/projects/' + saved['id']).json()
    assert detail['data']['desc'] == '梳理付款条款\n核对交付期限'
    listed = client.get('/api/workbench/projects').json()
    assert next(p for p in listed if p['id'] == saved['id'])['data']['desc'] == detail['data']['desc']
    assert client.post('/api/workbench/projects', json={'title': '过长', 'desc': '字' * 2001}, headers={'Idempotency-Key': new_id()}).status_code == 422


def test_court_context_is_scoped_and_marks_ai_drafts(client):
    p, other = project(client), project(client)
    with transaction() as s:
        s.add(Item(id='source-a',owner='alice',kind='conversation',project_id=p['id'],title='案情讨论',data={'messages':[{'role':'user','content':'付款争议'},{'role':'assistant','content':'待验证意见'},{'role':'tool','content':'密钥不应收集'}]}))
        s.add(Item(id='source-b',owner='alice',kind='conversation',project_id=other['id'],title='另一案件',data={'messages':[{'role':'user','content':'其他项目机密'}]}))
        s.add(Item(id='court-private',owner='alice',kind='court',project_id=p['id'],title='旧庭审',data={'session':{'private_brief':{'strategy':'隐藏策略'}}}))
    result = client.get('/api/workbench/projects/'+p['id']+'/court-context').json()
    assert [s['id'] for s in result['sources']] == ['source-a']
    assert 'AI 草稿（待核验）' in result['sources'][0]['text']
    assert '密钥' not in str(result) and '隐藏策略' not in str(result)
    client.app.dependency_overrides[get_current_user] = lambda: 'bob'
    assert client.get('/api/workbench/projects/'+p['id']+'/court-context').status_code == 404


def test_search_kind_and_space_filter(client):
    p = project(client)
    document(client, p)
    client.post(
        "/api/workbench/conversations",
        json={"title": "合同咨询", "project_id": p["id"]},
        headers={"Idempotency-Key": new_id()},
    )
    everything = client.get("/api/workbench/search", params={"q": "合同"}).json()
    assert {hit["kind"] for hit in everything} == {"document", "conversation"}
    files = client.get("/api/workbench/search", params={"q": "合同", "kind": "document"}).json()
    assert [hit["kind"] for hit in files] == ["document"]
    assert "付款期限" not in str(files[0]["data"])
    assert (
        client.get(
            "/api/workbench/search",
            params={"q": "合同", "kind": "document", "space": "personal"},
        ).json()
        == []
    )
    assert len(
        client.get("/api/workbench/search", params={"q": "合同", "space": p["id"]}).json()
    ) == 2
    assert (
        client.get("/api/workbench/search", params={"q": "合同", "kind": "court"}).status_code
        == 422
    )


def test_suggestions_degrade_and_rotate_without_materials(client):
    first = client.post("/api/workbench/suggestions", json={}).json()
    assert len(first["items"]) == 3 and first["degraded"] is True
    rotated = client.post("/api/workbench/suggestions", json={"refresh": True}).json()
    assert {item["title"] for item in rotated["items"]} != {
        item["title"] for item in first["items"]
    }
    for item in first["items"]:
        assert item["title"] and item["prompt"]


def test_suggestions_locale_reaches_the_model_prompt(client):
    """locale 只作用于生成提示：带 en-US 时提示里要有英文要求，缺省时提示原样。"""
    import function_calling
    from workbench import suggestions

    p = project(client)
    document(client, p)
    answer = SimpleNamespace(
        content='```json\n{"items":[{"title":"Review payment terms",'
        '"prompt":"Please review the payment terms and list the risks."}]}\n```'
    )
    with mock.patch.object(
        function_calling, "call", mock.AsyncMock(return_value=answer)
    ) as fake:
        generated = client.post(
            "/api/workbench/suggestions",
            json={"project_id": p["id"], "locale": "en-US"},
        ).json()
        assert generated["items"] == [
            {
                "title": "Review payment terms",
                "prompt": "Please review the payment terms and list the risks.",
            }
        ]
        assert fake.await_count == 1
        system = fake.await_args.args[0][0]["content"]
        assert "en-US" in system and "英文" in system
    # 不带 locale 的请求必须拿到未改动的系统提示，行为与旧版完全一致。
    with mock.patch.object(
        function_calling, "call", mock.AsyncMock(return_value=answer)
    ) as fake:
        client.post("/api/workbench/suggestions", json={"project_id": p["id"]})
        assert fake.await_count == 1
        assert fake.await_args.args[0][0]["content"] == suggestions.SYSTEM_PROMPT


def test_suggestions_use_model_then_cache_then_degrade(client, monkeypatch):
    import function_calling
    from workbench import suggestions

    monkeypatch.setattr(suggestions, "REFRESH_INTERVAL", 0)
    p = project(client)
    document(client, p)
    answer = SimpleNamespace(
        content='```json\n{"items":[{"title":"审查付款条款","prompt":"请审查付款条款并列出风险与修改建议。"}]}\n```'
    )
    with mock.patch.object(
        function_calling, "call", mock.AsyncMock(return_value=answer)
    ) as fake:
        generated = client.post(
            "/api/workbench/suggestions", json={"project_id": p["id"]}
        ).json()
        assert generated["items"] == [
            {"title": "审查付款条款", "prompt": "请审查付款条款并列出风险与修改建议。"}
        ]
        assert generated["degraded"] is False and fake.await_count == 1
        cached = client.post("/api/workbench/suggestions", json={"project_id": p["id"]}).json()
        assert cached["items"] == generated["items"] and fake.await_count == 1
        client.post(
            "/api/workbench/suggestions", json={"project_id": p["id"], "refresh": True}
        )
        assert fake.await_count == 2
        document(client, p)
        client.post("/api/workbench/suggestions", json={"project_id": p["id"]})
        assert fake.await_count == 3
    document(client, p)
    with mock.patch.object(
        function_calling, "call", mock.AsyncMock(side_effect=RuntimeError("模型不可用"))
    ):
        degraded = client.post(
            "/api/workbench/suggestions", json={"project_id": p["id"]}
        ).json()
        assert degraded["degraded"] is True and len(degraded["items"]) == 3


def test_project_court_snapshot_conflict_and_resume(client):
    p = project(client)
    snapshot = {'id':'trial-one','project_id':p['id'],'title':'模拟庭审','case_type':'civil','shared_dossier':{'summary':'公开事实'},'private_brief':{'strategy':'私有策略'},'court_state':{'phase':'opening'},'agent_states':{},'public_events':[],'pending_interjections':[],'auto_mode':True}
    payload = {'expected_revision':0,'project_id':p['id'],'session':snapshot}
    response = client.put('/api/workbench/courts/trial-one/snapshot',json=payload)
    assert response.status_code == 200
    assert response.json()['data']['session']['auto_mode'] is False
    assert client.put('/api/workbench/courts/trial-one/snapshot',json=payload).json()['revision'] == 1
    listing = client.get('/api/workbench/courts').json()
    assert '私有策略' not in str(listing)
    restored = client.get('/api/workbench/courts?include_session=true').json()[0]['data']['session']
    assert restored['project_id'] == p['id'] and restored['private_brief']['strategy'] == '私有策略'
    snapshot['shared_dossier']['summary'] = '修订事实'
    assert client.put('/api/workbench/courts/trial-one/snapshot',json=payload).status_code == 409
    payload['expected_revision'] = 1
    assert client.put('/api/workbench/courts/trial-one/snapshot',json=payload).json()['revision'] == 2
    client.app.dependency_overrides[get_current_user] = lambda: 'bob'
    assert client.get('/api/workbench/courts/trial-one').status_code == 404
    assert client.put('/api/workbench/courts/trial-one/snapshot',json=payload).status_code == 404


def test_suggestions_degrade_instead_of_failing(client):
    """首页建议是装饰性内容：素材层出错也必须给出静态建议，而不是 500。

    真实触发场景是「库还没跑迁移」——工作台的表不存在时，读素材会抛
    OperationalError；那与用户无关，不该让整个首页报错。
    """
    from workbench import suggestions
    from sqlalchemy.exc import OperationalError

    with mock.patch.object(
        suggestions, "material_digest", side_effect=OperationalError("no such table", None, None)
    ):
        response = client.post("/api/workbench/suggestions", json={"refresh": False})
    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert len(body["items"]) == 3
    assert all(item.get("title") and item.get("prompt") for item in body["items"])


def test_workbench_tables_self_heal_on_first_use(tmp_path, monkeypatch):
    """库没迁移时，第一次访问会补建工作台表，而不是一路 500。"""
    from sqlalchemy import inspect
    from infra import database
    from workbench import store

    monkeypatch.setenv("LAWVER_DATABASE_URL", "sqlite:///" + str(tmp_path / "cold.db"))
    monkeypatch.setenv("LAWVER_WORKBENCH_TESTING", "1")
    store._READY_URL = None  # 丢掉进程内缓存，模拟冷启动

    engine = store.engine_for(store.database_url())
    assert not inspect(engine).has_table("workbench_items")
    with store.transaction() as session:
        assert session.scalars(select(Item).limit(1)).all() == []
    assert inspect(engine).has_table("workbench_items")


def test_failed_restore_keeps_blobs_referenced_by_anyone(client):
    """恢复失败清理 written_blobs 前必须查引用：blob 按内容寻址、跨用户共享。

    顺序模拟并发恢复同一附件的交错窗口——先提交方（bob 的文档）已经引用了
    这个 blob；后失败方恢复同一附件并在 blob 落盘后因清单里混入坏条目而回滚。
    后失败方的清理绝不能删掉仍被引用的共享 blob。
    """
    import hashlib
    import io
    import json
    import zipfile

    from workbench.store import BlobStore

    payload = "并发双方共享的附件内容".encode()
    key = hashlib.sha256(payload).hexdigest()

    # 先提交方：已提交、引用该 blob 的文档（blob 文件是否已在盘上不重要——
    # 并发窗口里后失败方总是走「落盘前不存在」分支并记录该键）。
    with transaction() as s:
        s.add(
            Item(
                id="committed-doc",
                owner="bob",
                kind="document",
                title="已提交",
                revision=1,
                data={
                    "format": "pdf",
                    "blob_key": key,
                    "size": len(payload),
                    "mime": "application/pdf",
                },
            )
        )

    # 后失败方：同一 blob + 一个非法条目，让事务在 blob 落盘之后才失败。
    manifest = {
        "format": "lawver-workbench",
        "version": 5,
        "items": [
            {
                "id": "doc-b",
                "kind": "document",
                "title": "附件副本",
                "revision": 1,
                "data": {
                    "format": "pdf",
                    "blob_key": key,
                    "size": len(payload),
                    "mime": "application/pdf",
                },
            },
            {"id": "bad-item", "kind": "bogus", "title": "坏条目", "revision": 1, "data": {}},
        ],
        "versions": [],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        z.writestr("blobs/" + key, payload)

    response = client.post(
        "/api/workbench/backup",
        files={"file": ("broken.zip", buffer.getvalue(), "application/zip")},
        headers={"Idempotency-Key": "broken-restore"},
    )
    assert response.status_code == 422
    # 失败点必须是「坏条目」：说明 blob 已落盘、条目已入事务后才回滚。
    assert response.json()["detail"] == "不支持的内容类型"
    # blob 仍被先提交方引用：失败清理必须放过它。
    assert BlobStore().path(key).exists()


def test_unknown_family_404_uses_business_copy(client):
    """未知 family 的 404 要带业务文案，与同族「内容不存在或无权访问」一致。"""
    responses = [
        client.get("/api/workbench/widgets"),
        client.post("/api/workbench/widgets", json={"title": "x"}),
        client.get("/api/workbench/widgets/abc"),
        client.patch("/api/workbench/widgets/abc", json={"expected_revision": 1}),
        client.delete("/api/workbench/widgets/abc"),
    ]
    for response in responses:
        assert response.status_code == 404
        assert response.json()["detail"] == "内容不存在或无权访问"


def test_create_requires_and_honors_idempotency_key(client):
    """方向 A：创建类 POST 无条件强制幂等键；重放返回同一结果，换载荷报 409。"""
    missing = client.post("/api/workbench/documents", json={"title": "无键"})
    assert missing.status_code == 422
    assert missing.json()["detail"] == "需要有效的 Idempotency-Key"
    assert (
        client.post(
            "/api/workbench/documents",
            json={"title": "超长键"},
            headers={"Idempotency-Key": "k" * 129},
        ).status_code
        == 422
    )

    body = {"title": "合同"}
    first = client.post(
        "/api/workbench/documents", json=body, headers={"Idempotency-Key": "doc-1"}
    )
    assert first.status_code == 200, first.text
    replay = client.post(
        "/api/workbench/documents", json=body, headers={"Idempotency-Key": "doc-1"}
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert (
        client.post(
            "/api/workbench/documents",
            json={"title": "其他"},
            headers={"Idempotency-Key": "doc-1"},
        ).status_code
        == 409
    )
    # 幂等去重之后列表里仍然只有一条。
    assert len(client.get("/api/workbench/documents").json()) == 1


def _conversation_with_message(client):
    conv = client.post(
        "/api/workbench/conversations",
        json={"title": "咨询"},
        headers={"Idempotency-Key": new_id()},
    ).json()
    with transaction() as s:
        item = s.get(Item, conv["id"])
        item.data = {
            **item.data,
            "messages": [{"id": "m-1", "role": "user", "content": "材料"}],
        }
    return conv


def test_branch_upload_trash_restore_require_and_honor_key(client):
    """分支、上传、回收站恢复：无键 422，带键 200，重放同一结果。"""
    conv = _conversation_with_message(client)

    branch_body = {"message_id": "m-1", "title": "分支"}
    path = "/api/workbench/conversations/" + conv["id"] + "/branch"
    assert client.post(path, json=branch_body).status_code == 422
    first = client.post(path, json=branch_body, headers={"Idempotency-Key": "branch-1"})
    assert first.status_code == 200, first.text
    replay = client.post(path, json=branch_body, headers={"Idempotency-Key": "branch-1"})
    assert replay.json()["id"] == first.json()["id"]

    files = {"file": ("材料.txt", "上传内容".encode(), "text/plain")}
    assert client.post("/api/workbench/documents/upload", files=files).status_code == 422
    uploaded = client.post(
        "/api/workbench/documents/upload",
        files=files,
        headers={"Idempotency-Key": "upload-1"},
    )
    assert uploaded.status_code == 200, uploaded.text
    again = client.post(
        "/api/workbench/documents/upload",
        files=files,
        headers={"Idempotency-Key": "upload-1"},
    )
    assert again.json()["id"] == uploaded.json()["id"]

    deleted = project(client)
    client.delete("/api/workbench/projects/" + deleted["id"])
    restore_path = "/api/workbench/trash/" + deleted["id"] + "/restore"
    assert client.post(restore_path).status_code == 422
    restored = client.post(restore_path, headers={"Idempotency-Key": "undelete-1"})
    assert restored.status_code == 200, restored.text
    assert (
        client.post(restore_path, headers={"Idempotency-Key": "undelete-1"}).json()["id"]
        == deleted["id"]
    )


def test_document_restore_editable_confirmation_require_and_honor_key(client):
    """版本恢复、编辑副本、运行审批：无键 422，带键 200，重放同一结果。"""
    p = project(client)
    d = document(client, p)
    client.put(
        "/api/workbench/documents/" + d["id"] + "/content",
        json={"expected_revision": 1, "content": native("第二版。")},
    )

    restore_path = "/api/workbench/documents/" + d["id"] + "/restore-version"
    restore_body = {"expected_revision": 2, "revision": 1}
    assert client.post(restore_path, json=restore_body).status_code == 422
    first = client.post(
        restore_path, json=restore_body, headers={"Idempotency-Key": "rv-1"}
    )
    assert first.status_code == 200, first.text
    assert (
        client.post(restore_path, json=restore_body, headers={"Idempotency-Key": "rv-1"}).json()
        == first.json()
    )

    copy_path = "/api/workbench/documents/" + d["id"] + "/editable-copy"
    assert client.post(copy_path).status_code == 422
    copy = client.post(copy_path, headers={"Idempotency-Key": "copy-1"})
    assert copy.status_code == 200, copy.text
    assert (
        client.post(copy_path, headers={"Idempotency-Key": "copy-1"}).json()["id"]
        == copy.json()["id"]
    )

    conv = _conversation_with_message(client)
    with transaction() as s:
        s.add(
            Item(
                id="run-confirm",
                owner="alice",
                kind="run",
                parent_id=conv["id"],
                title="审批",
                data={
                    "status": "waiting_confirmation",
                    "confirmation": {"id": "call-1"},
                },
            )
        )
    approval_path = "/api/workbench/runs/run-confirm/confirmation"
    approval_body = {"call_id": "call-1", "allow": True}
    assert client.post(approval_path, json=approval_body).status_code == 422
    approved = client.post(
        approval_path, json=approval_body, headers={"Idempotency-Key": "approve-1"}
    )
    assert approved.status_code == 200, approved.text
    assert (
        client.post(
            approval_path, json=approval_body, headers={"Idempotency-Key": "approve-1"}
        ).json()
        == approved.json()
    )
    assert approved.json()["data"]["approval"] == approval_body


def test_backup_restore_requires_key_before_parsing_zip(client):
    """恢复的幂等键预检必须在 zip 解析之前：无键请求一个字节都不解析。"""
    files = {"file": ("broken.zip", b"this is not a zip archive", "application/zip")}
    missing = client.post("/api/workbench/backup", files=files)
    assert missing.status_code == 422
    assert missing.json()["detail"] == "需要有效的 Idempotency-Key"
    # 带键才走到解析：此时拿到的是格式错误，而不是键错误。
    parsed = client.post("/api/workbench/backup", files=files, headers={"Idempotency-Key": "restore-1"})
    assert parsed.status_code == 422
    assert parsed.json()["detail"] == "备份格式无效；旧版备份请从本地旧资料导入"


def test_listing_and_search_skip_items_whose_project_is_gone(client):
    """可达性批量复核与 get_item 同语义：项目进回收站后条目从列表与搜索消失。"""
    p = project(client)
    d = document(client, p)
    assert [x["id"] for x in client.get("/api/workbench/documents").json()] == [d["id"]]
    client.delete("/api/workbench/projects/" + p["id"])
    assert client.get("/api/workbench/documents").json() == []
    assert (
        client.get("/api/workbench/search", params={"q": "合同"}).json() == []
    )
    client.post(
        "/api/workbench/trash/" + p["id"] + "/restore",
        headers={"Idempotency-Key": new_id()},
    )
    assert [x["id"] for x in client.get("/api/workbench/documents").json()] == [d["id"]]


def test_listing_keyset_pagination_is_additive(client):
    """limit/cursor 任一出现才返回信封；都缺省时维持原数组形状与上限语义。"""
    p = project(client)
    titles = {f"文档{i}" for i in range(5)}
    for title in sorted(titles):
        r = client.post(
            "/api/workbench/documents",
            json={"title": title, "project_id": p["id"], "content": native("内容")},
            headers={"Idempotency-Key": new_id()},
        )
        assert r.status_code == 200, r.text

    legacy = client.get("/api/workbench/documents")
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 5

    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/api/workbench/documents", params=params)
        assert response.status_code == 200
        envelope = response.json()
        assert set(envelope) == {"items", "next_cursor"}
        seen.extend(item["title"] for item in envelope["items"])
        pages += 1
        if not envelope["next_cursor"]:
            break
        cursor = envelope["next_cursor"]
        assert pages < 10
    assert pages == 3
    assert len(seen) == len(set(seen)) == 5
    assert set(seen) == titles

    # 只带 cursor（不带 limit）同样走信封：默认页大小一次取完剩余行。
    first = client.get("/api/workbench/documents", params={"limit": 2}).json()
    rest = client.get(
        "/api/workbench/documents", params={"cursor": first["next_cursor"]}
    ).json()
    assert set(rest) == {"items", "next_cursor"}
    assert rest["next_cursor"] == ""
    assert {item["title"] for item in rest["items"]} == titles - {
        item["title"] for item in first["items"]
    }

    assert (
        client.get("/api/workbench/documents", params={"limit": 0}).status_code == 422
    )
    assert (
        client.get("/api/workbench/documents", params={"limit": 201}).status_code == 422
    )
    assert (
        client.get("/api/workbench/documents", params={"cursor": "无关字符串"}).status_code
        == 422
    )


def test_search_keyset_pagination_is_additive(client):
    p = project(client)
    for index in range(4):
        r = client.post(
            "/api/workbench/documents",
            json={
                "title": f"合同{index}",
                "project_id": p["id"],
                "content": native("条款"),
            },
            headers={"Idempotency-Key": new_id()},
        )
        assert r.status_code == 200, r.text

    legacy = client.get("/api/workbench/search", params={"q": "合同"})
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 4

    first = client.get("/api/workbench/search", params={"q": "合同", "limit": 3})
    assert first.status_code == 200
    envelope = first.json()
    assert set(envelope) == {"items", "next_cursor"}
    assert len(envelope["items"]) == 3 and envelope["next_cursor"]
    rest = client.get(
        "/api/workbench/search",
        params={"q": "合同", "cursor": envelope["next_cursor"]},
    ).json()
    assert set(rest) == {"items", "next_cursor"}
    assert rest["next_cursor"] == ""
    ids = [item["id"] for item in envelope["items"] + rest["items"]]
    assert len(ids) == len(set(ids)) == 4
