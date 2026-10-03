"""Portable account backup v5, excluding connector credentials."""

import asyncio
import copy
import io
import json
import zipfile
import hashlib
from fastapi import APIRouter, Depends, UploadFile, File, Header, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from workbench.api import gate, receipt
from workbench.store import Item, Version, BlobStore, transaction, new_id, public
from workbench.documents import validate_content

router = APIRouter(prefix="/api/workbench/backup", tags=["backup"])


@router.get("")
def export(user=Depends(gate)):
    out = io.BytesIO()
    with transaction() as s:
        items = s.scalars(
            select(Item).where(
                Item.owner == user,
                Item.kind.in_(
                    [
                        "project",
                        "conversation",
                        "document",
                        "proposal",
                        "skill",
                        "connector",
                        "court_archive",
                        "court",
                    ]
                ),
            )
        ).all()
        versions = s.scalars(select(Version).where(Version.owner == user)).all()
        data = {"format": "lawver-workbench", "version": 5, "items": [], "versions": []}
        keys = set()
        for item in items:
            value = public(item)
            value["data"] = copy.deepcopy(item.data)
            value["data"].pop("encrypted_secret", None)
            if item.kind == "connector":
                value["data"]["enabled"] = False
            if value["data"].get("blob_key"):
                keys.add(value["data"]["blob_key"])
            data["items"].append(value)
        for v in versions:
            data["versions"].append(
                {"document_id": v.document_id, "revision": v.revision, "data": v.data}
            )
            if v.data.get("blob_key"):
                keys.add(v.data["blob_key"])
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(data, ensure_ascii=False))
            for key in keys:
                path = BlobStore().path(key)
                if not path.exists():
                    raise HTTPException(409, "有附件缺失，不能生成完整备份")
                z.writestr("blobs/" + key, path.read_bytes())
    return Response(
        out.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="lawver-workbench-v5.zip"'
        },
    )


@router.post("")
async def restore(
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    raw = await file.read(256 * 1024 * 1024 + 1)
    if len(raw) > 256 * 1024 * 1024:
        raise HTTPException(413, "备份超过 256 MB，请分批恢复")
    # 解压校验（最多 512 MB）、逐个附件哈希落盘、整批建条目都是阻塞操作，
    # 在 async 端点里直接做会把事件循环卡住几十秒：整段放进线程。
    return await asyncio.to_thread(_restore_backup, raw, idempotency_key, user)


def _restore_backup(raw: bytes, idempotency_key: str | None, user: str):
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        if sum(f.file_size for f in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError()
        data = json.loads(archive.read("manifest.json"))
        if data.get("format") != "lawver-workbench" or data.get("version") != 5:
            raise ValueError()
    except Exception:
        raise HTTPException(422, "备份格式无效；旧版备份请从本地旧资料导入")
    with transaction() as s:

        def apply():
            ids = {x["id"]: new_id() for x in data["items"]}
            if len(ids) != len(data["items"]):
                raise HTTPException(422, "重复的内容标识")
            allowed = {
                "project",
                "conversation",
                "document",
                "proposal",
                "skill",
                "connector",
                "court_archive",
                "court",
            }

            def rewrite(value):
                if isinstance(value, str):
                    return ids.get(value, value)
                if isinstance(value, list):
                    return [rewrite(x) for x in value]
                if isinstance(value, dict):
                    return {
                        k: rewrite(v)
                        for k, v in value.items()
                        if k != "encrypted_secret"
                    }
                return value

            def check_doc(value):
                if value.get("format") == "native":
                    validate_content(value["content"])
                if value.get("blob_key"):
                    key = value["blob_key"]
                    BlobStore().path(key)
                    blob = archive.read("blobs/" + key)
                    if hashlib.sha256(blob).hexdigest() != key:
                        raise HTTPException(422, "附件校验失败")
                    BlobStore().put(blob)

            for x in data["items"]:
                if x["kind"] not in allowed:
                    raise HTTPException(422, "不支持的内容类型")
                value = rewrite(x["data"])
                if x["kind"] == "document":
                    check_doc(value)
                if x["kind"] == "connector":
                    value.update(enabled=False, tools=[])
                item = Item(
                    id=ids[x["id"]],
                    owner=user,
                    kind=x["kind"],
                    title=str(x["title"])[:300],
                    project_id=ids.get(x.get("project_id")),
                    parent_id=ids.get(x.get("parent_id")),
                    revision=int(x["revision"]),
                    data=value,
                )
                s.add(item)
            for v in data.get("versions", []):
                if v["document_id"] not in ids:
                    continue
                value = rewrite(v["data"])
                check_doc(value)
                s.add(
                    Version(
                        document_id=ids[v["document_id"]],
                        owner=user,
                        revision=v["revision"],
                        data=value,
                    )
                )
            return {
                "restored": len(ids),
                "message": "资料已恢复为新的副本，插件需要重新配置密钥和启用",
            }

        return receipt(
            s, user, idempotency_key, {"sha256": hashlib.sha256(raw).hexdigest()}, apply
        )
