import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from workbench.api import router
from workbench.store import Base, engine_for, database_url, transaction, Item, new_id
from workbench.documents import native
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
    return c.post("/api/v2/projects", json={"title": "测试项目"}).json()


def document(c, p):
    return c.post(
        "/api/v2/documents",
        json={
            "title": "合同",
            "project_id": p["id"],
            "content": native("付款期限为三十日。\n双方应保密。"),
        },
    ).json()


def test_version_conflict_and_restore(client):
    p = project(client)
    d = document(client, p)
    r = client.put(
        "/api/v2/documents/" + d["id"] + "/content",
        json={"expected_revision": 1, "content": native("付款期限为十五日。")},
    )
    assert r.status_code == 200
    assert r.json()["revision"] == 2
    r = client.put(
        "/api/v2/documents/" + d["id"] + "/content",
        json={"expected_revision": 1, "content": native("不应覆盖")},
    )
    assert r.status_code == 409
    r = client.post(
        "/api/v2/documents/" + d["id"] + "/restore-version",
        json={"expected_revision": 2, "revision": 1},
    )
    assert r.status_code == 200
    assert r.json()["revision"] == 3
    assert "三十日" in str(r.json()["data"]["content"])


def test_owner_project_context_and_idempotency(client):
    p = project(client)
    d = document(client, p)
    q = project(client)
    c = client.post(
        "/api/v2/conversations", json={"title": "咨询", "project_id": p["id"]}
    ).json()
    body = {
        "conversation_id": c["id"],
        "message": "审查",
        "references": [{"kind": "document", "id": d["id"], "revision": 1}],
    }
    r = client.post("/api/v2/runs", json=body, headers={"Idempotency-Key": "run-1"})
    assert r.status_code == 200, r.text
    assert (
        client.post(
            "/api/v2/runs", json=body, headers={"Idempotency-Key": "run-1"}
        ).json()["id"]
        == r.json()["id"]
    )
    assert (
        client.post(
            "/api/v2/runs",
            json={**body, "message": "其他"},
            headers={"Idempotency-Key": "run-1"},
        ).status_code
        == 409
    )
    client.app.dependency_overrides[get_current_user] = lambda: "bob"
    assert client.get("/api/v2/documents/" + d["id"]).status_code == 404
    client.app.dependency_overrides[get_current_user] = lambda: "alice"
    c2 = client.post(
        "/api/v2/conversations", json={"title": "其他", "project_id": q["id"]}
    ).json()
    assert (
        client.post(
            "/api/v2/runs",
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
        "/api/v2/change-proposals/" + ids[0] + "/decision",
        json=body,
        headers={"Idempotency-Key": "accept-1"},
    )
    assert r.status_code == 200, r.text
    assert (
        client.post(
            "/api/v2/change-proposals/" + ids[0] + "/decision",
            json=body,
            headers={"Idempotency-Key": "accept-1"},
        ).json()
        == r.json()
    )
    r = client.post(
        "/api/v2/change-proposals/" + ids[1] + "/decision",
        json={"expected_revision": 2, "action": "accept"},
        headers={"Idempotency-Key": "accept-2"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["document"]["revision"] == 3


def test_delete_conversation_retains_project_file(client):
    p = project(client)
    d = document(client, p)
    c = client.post(
        "/api/v2/conversations", json={"title": "咨询", "project_id": p["id"]}
    ).json()
    assert client.delete("/api/v2/conversations/" + c["id"]).status_code == 200
    assert client.get("/api/v2/documents/" + d["id"]).status_code == 200
    assert client.delete("/api/v2/projects/" + p["id"]).status_code == 200
    assert client.get("/api/v2/documents/" + d["id"]).status_code == 404
    assert client.post("/api/v2/trash/" + p["id"] + "/restore").status_code == 200
    assert client.get("/api/v2/documents/" + d["id"]).status_code == 200


def test_upload_and_native_export(client):
    p = project(client)
    r = client.post(
        "/api/v2/documents/upload",
        data={"project_id": p["id"]},
        files={"file": ("材料.txt", "测试材料".encode(), "text/plain")},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert "blob_key" not in d["data"]
    assert (
        client.get("/api/v2/documents/" + d["id"] + "/blob").content
        == "测试材料".encode()
    )
    copy = client.post("/api/v2/documents/" + d["id"] + "/editable-copy").json()
    assert (
        client.get("/api/v2/documents/" + copy["id"] + "/export").content[:2] == b"PK"
    )


def test_plugin_rejects_non_https_and_private_dns(client):
    assert (
        client.post(
            "/api/v2/connectors",
            json={"title": "不安全", "url": "http://localhost/mcp"},
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
    assert client.get("/api/v2/documents/" + d["id"]).status_code == 200
    assert client.get("/api/v2/documents/" + d["id"] + "/export").status_code == 200
    assert (
        client.put(
            "/api/v2/documents/" + d["id"] + "/content",
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
        "/api/v2/documents/" + d["id"] + "/content",
        json={
            "expected_revision": 1,
            "content": native("付款期限为三十日。\n另一设备追加内容。"),
        },
    )
    r = client.post(
        "/api/v2/change-proposals/" + identifier + "/decision",
        json={"expected_revision": 2, "action": "accept"},
        headers={"Idempotency-Key": "stale"},
    )
    assert r.status_code == 409
    assert "另一设备" in str(client.get("/api/v2/documents/" + d["id"]).json())


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
        "/api/v2/migrations", json=payload, headers={"Idempotency-Key": "migration"}
    )
    assert r.status_code == 200, r.text
    migration = r.json()
    path = "/api/v2/migrations/" + migration["id"] + "/files"
    data = {"conversation_id": "old", "original_path": "TEMP/old/材料.txt"}
    files = {"file": ("材料.txt", "虚构材料".encode(), "text/plain")}
    first = client.post(path, data=data, files=files)
    second = client.post(path, data=data, files=files)
    assert first.status_code == 200, first.text
    assert first.json()["id"] == second.json()["id"]
    backup = client.get("/api/v2/backup")
    assert backup.status_code == 200, backup.text[:200]
    r = client.post(
        "/api/v2/backup",
        files={"file": ("backup.zip", backup.content, "application/zip")},
        headers={"Idempotency-Key": "restore"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["restored"] >= 3


def test_project_optional_description_roundtrip(client):
    plain = project(client)
    assert plain['data']['desc'] == ''
    response = client.post('/api/v2/projects', json={'title': '合同审查', 'desc': '  梳理付款条款\n核对交付期限  '})
    assert response.status_code == 200
    saved = response.json()
    detail = client.get('/api/v2/projects/' + saved['id']).json()
    assert detail['data']['desc'] == '梳理付款条款\n核对交付期限'
    listed = client.get('/api/v2/projects').json()
    assert next(p for p in listed if p['id'] == saved['id'])['data']['desc'] == detail['data']['desc']
    assert client.post('/api/v2/projects', json={'title': '过长', 'desc': '字' * 2001}).status_code == 422


def test_court_context_is_scoped_and_marks_ai_drafts(client):
    p, other = project(client), project(client)
    with transaction() as s:
        s.add(Item(id='source-a',owner='alice',kind='conversation',project_id=p['id'],title='案情讨论',data={'messages':[{'role':'user','content':'付款争议'},{'role':'assistant','content':'待验证意见'},{'role':'tool','content':'密钥不应收集'}]}))
        s.add(Item(id='source-b',owner='alice',kind='conversation',project_id=other['id'],title='另一案件',data={'messages':[{'role':'user','content':'其他项目机密'}]}))
        s.add(Item(id='court-private',owner='alice',kind='court',project_id=p['id'],title='旧庭审',data={'session':{'private_brief':{'strategy':'隐藏策略'}}}))
    result = client.get('/api/v2/projects/'+p['id']+'/court-context').json()
    assert [s['id'] for s in result['sources']] == ['source-a']
    assert 'AI 草稿（待核验）' in result['sources'][0]['text']
    assert '密钥' not in str(result) and '隐藏策略' not in str(result)
    client.app.dependency_overrides[get_current_user] = lambda: 'bob'
    assert client.get('/api/v2/projects/'+p['id']+'/court-context').status_code == 404


def test_project_court_snapshot_conflict_and_resume(client):
    p = project(client)
    snapshot = {'id':'trial-one','project_id':p['id'],'title':'模拟庭审','case_type':'civil','shared_dossier':{'summary':'公开事实'},'private_brief':{'strategy':'私有策略'},'court_state':{'phase':'opening'},'agent_states':{},'public_events':[],'pending_interjections':[],'auto_mode':True}
    payload = {'expected_revision':0,'project_id':p['id'],'session':snapshot}
    response = client.put('/api/v2/courts/trial-one/snapshot',json=payload)
    assert response.status_code == 200
    assert response.json()['data']['session']['auto_mode'] is False
    assert client.put('/api/v2/courts/trial-one/snapshot',json=payload).json()['revision'] == 1
    listing = client.get('/api/v2/courts').json()
    assert '私有策略' not in str(listing)
    restored = client.get('/api/v2/courts?include_session=true').json()[0]['data']['session']
    assert restored['project_id'] == p['id'] and restored['private_brief']['strategy'] == '私有策略'
    snapshot['shared_dossier']['summary'] = '修订事实'
    assert client.put('/api/v2/courts/trial-one/snapshot',json=payload).status_code == 409
    payload['expected_revision'] = 1
    assert client.put('/api/v2/courts/trial-one/snapshot',json=payload).json()['revision'] == 2
    client.app.dependency_overrides[get_current_user] = lambda: 'bob'
    assert client.get('/api/v2/courts/trial-one').status_code == 404
    assert client.put('/api/v2/courts/trial-one/snapshot',json=payload).status_code == 404
