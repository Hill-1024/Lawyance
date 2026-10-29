from datetime import datetime, timedelta
import hashlib

import pytest
from sqlalchemy import select

from test_workbench_conversation_export import client, _conversation, _rich_messages
from workbench import sharing
from workbench.store import ConversationShare, Item, Receipt, transaction, new_id
from services.auth_dependencies import get_current_user


@pytest.fixture
def shared_client(client):
    client.app.include_router(sharing.router)
    return client


def create(client, conv, days=30, key=None):
    response = client.post(f"/api/workbench/conversations/{conv['id']}/share",
                           json={"days": days}, headers={"Idempotency-Key": key or new_id()})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("days", [7, 14, 21, 30])
def test_public_snapshot_expiry_choices_and_private_fields(shared_client, days):
    c = shared_client
    conv = _conversation(c, "分享测试", _rich_messages())
    share = create(c, conv, days)
    assert datetime.fromisoformat(share["expires_at"]) - datetime.fromisoformat(share["created_at"]) == timedelta(days=days)
    with transaction() as s:
        s.get(Item, conv["id"]).data = {"messages": [{"role": "user", "content": "later private message"}]}
    c.app.dependency_overrides[get_current_user] = lambda: pytest.fail("Public shares must not authenticate")
    response = c.get(f"/api/shares/{share['token']}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "noindex" in response.headers["x-robots-tag"]
    assert set(response.json()) == {"title", "messages", "expires_at"}
    assert "trace" not in response.text and "TOOL_RAW_OUTPUT_SECRET" not in response.text
    assert "later private message" not in response.text
    assert all(set(m) == {"role", "content", "created_at"} for m in response.json()["messages"])
    status = c.get(f"/api/shares/{share['token']}/status")
    assert status.status_code == 200 and set(status.json()) == {"expires_at"}


def test_owner_access_and_token_bound_revocation(shared_client):
    c = shared_client
    conv = _conversation(c, "所有者", _rich_messages())
    base = f"/api/workbench/conversations/{conv['id']}/share"
    original = create(c, conv)
    c.app.dependency_overrides[get_current_user] = lambda: "bob"
    assert c.get(base).status_code == 404
    assert c.post(base, json={}, headers={"Idempotency-Key": new_id()}).status_code == 404
    assert c.delete(f"{base}/{original['token']}").status_code == 404
    assert c.get(f"/api/shares/{original['token']}").status_code == 200
    del c.app.dependency_overrides[get_current_user]
    assert c.get(base).status_code == 401
    assert c.post(base, json={}, headers={"Idempotency-Key": new_id()}).status_code == 401
    assert c.delete(f"{base}/{original['token']}").status_code == 401
    c.app.dependency_overrides[get_current_user] = lambda: "alice"
    assert c.delete(f"{base}/{original['token']}").json()["status"] == "revoked"
    assert c.delete(f"{base}/{original['token']}").status_code == 200
    assert c.get(f"/api/shares/{original['token']}").status_code == 404
    assert c.get(f"/api/shares/{original['token']}/status").status_code == 404
    with transaction() as s:
        assert s.get(ConversationShare, conv["id"]).snapshot == {}
    new = create(c, conv)
    assert new["token"] != original["token"]
    assert c.delete(f"{base}/{original['token']}").status_code == 409
    assert c.get(f"/api/shares/{new['token']}").status_code == 200


def test_idempotency_never_resurrects_revoked_snapshot(shared_client):
    c = shared_client
    conv = _conversation(c, "幂等", _rich_messages())
    base = f"/api/workbench/conversations/{conv['id']}/share"
    key = new_id()
    assert c.post(base, json={}).status_code == 422
    first = create(c, conv, key=key)
    assert create(c, conv, key=key) == first
    assert create(c, conv) == first
    assert c.post(base, json={"days": 7}, headers={"Idempotency-Key": key}).status_code == 409
    c.delete(f"{base}/{first['token']}")
    assert c.post(base, json={"days": 30}, headers={"Idempotency-Key": key}).status_code == 409
    second = create(c, conv)
    assert c.post(base, json={"days": 30}, headers={"Idempotency-Key": key}).status_code == 409
    assert second["token"] != first["token"]
    with transaction() as s:
        assert len(s.scalars(select(ConversationShare)).all()) == 1
        receipt_id = hashlib.sha256(("alice:" + key).encode()).hexdigest()
        assert s.get(Receipt, receipt_id).result == {"token": first["token"]}


def test_exact_expiry_clears_snapshot_and_recreate_rotates_token(shared_client, monkeypatch):
    c = shared_client
    conv = _conversation(c, "过期", _rich_messages())
    share = create(c, conv, days=7)
    expiry = datetime.fromisoformat(share["expires_at"])
    monkeypatch.setattr(sharing, "now", lambda: expiry - timedelta(microseconds=1))
    assert c.get(f"/api/shares/{share['token']}").status_code == 200
    monkeypatch.setattr(sharing, "now", lambda: expiry)
    assert c.get(f"/api/shares/{share['token']}").status_code == 404
    assert c.get(f"/api/shares/{share['token']}/status").status_code == 404
    assert c.get(f"/api/workbench/conversations/{conv['id']}/share").json()["status"] == "expired"
    sharing.purge_expired_shares()
    with transaction() as s:
        assert s.get(ConversationShare, conv["id"]).snapshot == {}
    assert create(c, conv)["token"] != share["token"]


@pytest.mark.parametrize("delete_project", [False, True])
def test_trash_and_restore_never_restore_public_access(shared_client, delete_project):
    c = shared_client
    conv = _conversation(c, "删除", _rich_messages())
    target, family = conv["id"], "conversations"
    if delete_project:
        target = c.post("/api/workbench/projects", json={"title": "project"}, headers={"Idempotency-Key": new_id()}).json()["id"]
        family = "projects"
        with transaction() as s:
            s.get(Item, conv["id"]).project_id = target
    share = create(c, conv)
    assert c.delete(f"/api/workbench/{family}/{target}").status_code == 200
    assert c.get(f"/api/shares/{share['token']}").status_code == 404
    with transaction() as s:
        s.get(Item, target).deleted_at = None
    assert c.get(f"/api/shares/{share['token']}").status_code == 404


def test_empty_running_and_invalid_expiry_rejected(shared_client):
    c = shared_client
    empty = _conversation(c, "empty", [])
    assert c.post(f"/api/workbench/conversations/{empty['id']}/share", json={}, headers={"Idempotency-Key": new_id()}).status_code == 422
    conv = _conversation(c, "pending", _rich_messages())
    with transaction() as s:
        s.add(Item(owner="alice", kind="run", parent_id=conv["id"], title="run", data={"status": "waiting_user"}))
    path = f"/api/workbench/conversations/{conv['id']}/share"
    assert c.post(path, json={}, headers={"Idempotency-Key": new_id()}).status_code == 409
    assert c.post(path, json={"days": 999}, headers={"Idempotency-Key": new_id()}).status_code == 422
    assert c.get(f"/api/workbench/conversations/{conv['id']}/export").status_code == 409


def test_public_rate_limit(shared_client, monkeypatch):
    from services import rate_limit

    monkeypatch.setattr(rate_limit, "hit", lambda *a, **kw: rate_limit.RateLimitResult(False, 91, 90, 30))
    response = shared_client.get(f"/api/shares/{new_id()}")
    assert response.status_code == 429 and response.headers["retry-after"] == "30"


def test_docx_is_immediate_and_creates_no_share_or_file(shared_client):
    c = shared_client
    conv = _conversation(c, "即时下载", _rich_messages())
    from workbench.store import BlobStore
    before = list(BlobStore().root.rglob("*"))
    assert c.get(f"/api/workbench/conversations/{conv['id']}/export").status_code == 200
    assert list(BlobStore().root.rglob("*")) == before
    with transaction() as s:
        assert s.get(ConversationShare, conv["id"]) is None


def test_migration_creates_expected_schema_and_is_repeatable(tmp_path):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect

    spec = importlib.util.spec_from_file_location("share_migration", Path(__file__).resolve().parents[1] / "backend/migrations/versions/20261029_conversation_shares.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        columns = {c["name"] for c in inspect(connection).get_columns("workbench_conversation_shares")}
        assert columns == set(ConversationShare.__table__.columns.keys())
        assert {tuple(c["column_names"]) for c in inspect(connection).get_unique_constraints("workbench_conversation_shares")} == {("token",)}
    engine.dispose()
