"""Additive, retryable imports; original browser data is never deleted."""

import hashlib
import json
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import Field
from sqlalchemy import select
from workbench.api import Body, gate, receipt
from workbench.store import Item, transaction, new_id, public

router = APIRouter(prefix="/api/v2/migrations", tags=["migration"])


class Import(Body):
    source_id: str = Field(max_length=200)
    conversations: list[dict] = Field(max_length=500)
    court_sessions: list[dict] = Field(default_factory=list, max_length=100)
    files: list[dict] = Field(default_factory=list, max_length=1000)


@router.post("")
def migrate(
    body: Import, idempotency_key: str | None = Header(None), user=Depends(gate)
):
    if len(json.dumps(body.model_dump())) > 20_000_000:
        raise HTTPException(413, "请分批迁移资料")
    with transaction() as s:

        def action():
            ids = {str(c["id"]): new_id() for c in body.conversations if c.get("id")}
            if len(ids) != len(body.conversations):
                raise HTTPException(422, "会话标识重复或缺失")
            roots = {}
            projects = {}
            missing = []
            source = {str(c["id"]): c for c in body.conversations}
            for identifier in source:
                root = identifier
                seen = set()
                while source[root].get("parent_id") in source:
                    if root in seen:
                        raise HTTPException(422, "分支关系存在循环")
                    seen.add(root)
                    root = source[root]["parent_id"]
                roots[identifier] = root
                if root not in projects:
                    p = Item(
                        id=new_id(),
                        owner=user,
                        kind="project",
                        title=source[root].get("title", "迁移资料")[:300],
                        data={"migration_source": body.source_id},
                    )
                    s.add(p)
                    projects[root] = p.id
            mapping = {}
            for old in body.conversations:
                identifier = str(old["id"])
                pid = projects[roots[identifier]]
                messages = []
                for m in old.get("messages", []):
                    messages.append(
                        {**m, "id": str(m.get("id") or new_id()), "legacy": True}
                    )
                item = Item(
                    id=ids[identifier],
                    owner=user,
                    kind="conversation",
                    project_id=pid,
                    parent_id=ids.get(old.get("parent_id")),
                    title=old.get("title", "迁移会话")[:300],
                    data={
                        "messages": messages,
                        "branch_point_message_id": old.get("branch_point_message_id"),
                        "legacy_snapshot": old,
                        "migration_source": body.source_id,
                    },
                )
                s.add(item)
                mapping[identifier] = {"conversation_id": item.id, "project_id": pid}
            for court in body.court_sessions:
                s.add(
                    Item(
                        id=new_id(),
                        owner=user,
                        kind="court_archive",
                        title=str(court.get("title", "庭审记录"))[:300],
                        data={
                            "legacy_snapshot": court,
                            "migration_source": body.source_id,
                        },
                    )
                )
            for f in body.files:
                if not f.get("available"):
                    missing.append(
                        {
                            "name": f.get("name"),
                            "path": f.get("path"),
                            "conversation_id": f.get("conversation_id"),
                        }
                    )
            migration = Item(
                id=new_id(),
                owner=user,
                kind="migration",
                title="本地资料迁移",
                data={
                    "source_id": body.source_id,
                    "mapping": mapping,
                    "missing_files": missing,
                    "file_manifest": body.files,
                    "status": "awaiting_files" if body.files else "complete",
                    "court_count": len(body.court_sessions),
                },
            )
            s.add(migration)
            s.flush()
            return public(migration)

        return receipt(s, user, idempotency_key, body.model_dump(), action)


@router.get("")
def list_migrations(user=Depends(gate)):
    with transaction() as s:
        return [
            public(x)
            for x in s.scalars(
                select(Item).where(Item.owner == user, Item.kind == "migration")
            )
        ]


from fastapi import UploadFile, File, Form
from workbench.store import get_item, BlobStore, now
from workbench.documents import extract, save_version, MAX_UPLOAD
import asyncio


@router.post("/{identifier}/files")
async def migrate_file(
    identifier: str,
    file: UploadFile = File(...),
    conversation_id: str = Form(...),
    original_path: str = Form(...),
    user=Depends(gate),
):
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "附件超出 32 MB")
    digest = hashlib.sha256(raw).hexdigest()
    key = hashlib.sha256(
        (identifier + conversation_id + original_path).encode()
    ).hexdigest()
    converted = await asyncio.to_thread(extract, raw, file.filename or "附件.txt")
    with transaction() as s:

        def apply():
            migration = get_item(s, user, identifier, "migration", lock=True)
            mapping = migration.data["mapping"].get(conversation_id)
            if not mapping:
                raise HTTPException(404, "未找到迁移会话")
            data = {
                **converted,
                "blob_key": BlobStore().put(raw),
                "size": len(raw),
                "mime": file.content_type,
                "legacy_path": original_path,
            }
            item = Item(
                id=new_id(),
                owner=user,
                kind="document",
                project_id=mapping["project_id"],
                title=(file.filename or "迁移附件")[:300],
                revision=1,
                data=data,
                searchable=data.get("text", ""),
            )
            s.add(item)
            s.flush()
            save_version(s, item)
            completed = {
                **migration.data.get("completed_files", {}),
                key: {
                    "document_id": item.id,
                    "checksum": digest,
                    "path": original_path,
                },
            }
            expected = sum(
                1 for f in migration.data["file_manifest"] if f.get("available")
            )
            migration.data = {
                **migration.data,
                "completed_files": completed,
                "status": "complete_with_missing"
                if len(completed) >= expected and migration.data["missing_files"]
                else "complete"
                if len(completed) >= expected
                else "awaiting_files",
            }
            conv = get_item(
                s, user, mapping["conversation_id"], "conversation", lock=True
            )
            conv.data = {
                **conv.data,
                "legacy_file_ids": {
                    **conv.data.get("legacy_file_ids", {}),
                    original_path: item.id,
                },
            }
            return public(item)

        return receipt(
            s,
            user,
            "migration-file-" + key,
            {"checksum": digest, "path": original_path},
            apply,
        )
