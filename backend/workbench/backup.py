"""Portable account backup v5, excluding connector credentials."""

import asyncio
import copy
import json
import os
import tempfile
import zipfile
import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, UploadFile, File, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from workbench.api import gate, receipt
from workbench.store import Item, Version, BlobStore, transaction, new_id, public
from workbench.documents import validate_content

router = APIRouter(prefix="/api/workbench/backup", tags=["backup"])

BACKUP_MAX_BYTES = 256 * 1024 * 1024


class BackupItem(BaseModel):
    id: str
    kind: str
    title: str
    revision: int
    data: dict
    project_id: str | None = None
    parent_id: str | None = None


class BackupVersion(BaseModel):
    document_id: str
    revision: int
    data: dict


class BackupManifest(BaseModel):
    """manifest 形状契约：缺键/类型不对在这里以 422 拒绝，而不是事务中途冒 500。"""

    format: Literal["lawver-workbench"]
    version: Literal[5]
    items: list[BackupItem]
    versions: list[BackupVersion] = Field(default_factory=list)


def _stream_sha256(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


@router.get("")
def export(user=Depends(gate)):
    # 事务里只收集 manifest 与 blob 键列表；blob 字节与 zip 编码移出事务、流式写临时
    # 文件再分块回传。此前 io.BytesIO 全内存构建：工作区接近恢复接口允许的 256MB 时，
    # 单次导出内存峰值即数百 MB、两个并发导出可拖垮进程，且整个构建期攥着同一个
    # DB 快照（Postgres 长事务）。restore 侧早已流式化，导出侧对齐。
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

    store = BlobStore()
    missing = [key for key in sorted(keys) if not store.path(key).exists()]
    if missing:
        raise HTTPException(409, "有附件缺失，不能生成完整备份")

    fd, out_path = tempfile.mkstemp(prefix="lawver-backup-", suffix=".zip")
    os.close(fd)
    try:
        # ZipFile.write 对每个 blob 分块读盘压缩，进程内存只占压缩缓冲区。
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(data, ensure_ascii=False))
            for key in sorted(keys):
                z.write(store.path(key), arcname="blobs/" + key)

        def stream():
            try:
                with open(out_path, "rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        yield chunk
            finally:
                # 客户端中途断开时 Starlette 会 close 生成器，finally 照样清理。
                try:
                    os.unlink(out_path)
                except OSError:
                    pass

        return StreamingResponse(
            stream(),
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="lawver-workbench-v5.zip"'
            },
        )
    except Exception:
        try:
            os.unlink(out_path)
        except OSError:
            pass
        raise


@router.post("")
async def restore(
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    # 上传体已在 Starlette 的 SpooledTemporaryFile 里（超限自动落盘）：这里只探测
    # 大小、把文件对象交给线程流式处理，256 MB 的压缩包不再整块读进内存。
    file.file.seek(0, os.SEEK_END)
    if file.file.tell() > BACKUP_MAX_BYTES:
        raise HTTPException(413, "备份超过 256 MB，请分批恢复")
    file.file.seek(0)
    # 解压校验（最多 512 MB）、逐个附件哈希落盘、整批建条目都是阻塞操作，
    # 在 async 端点里直接做会把事件循环卡住几十秒：整段放进线程。
    return await asyncio.to_thread(_restore_backup, file.file, idempotency_key, user)


def _restore_backup(stream, idempotency_key: str | None, user: str):
    fingerprint = _stream_sha256(stream)
    stream.seek(0)
    try:
        archive = zipfile.ZipFile(stream)
        if sum(f.file_size for f in archive.infolist()) > 512 * 1024 * 1024:
            raise ValueError()
        manifest = BackupManifest.model_validate(json.loads(archive.read("manifest.json")))
    except Exception:
        raise HTTPException(422, "备份格式无效；旧版备份请从本地旧资料导入")

    # 本次恢复新落盘的 blob 键：事务中途失败回滚后，这些文件成无人引用的孤儿，
    # 逐个清掉。只在「落盘前不存在」时记录——与他人共享的既有 blob 不能动。
    written_blobs: set[str] = set()
    try:
        with transaction() as s:

            def apply():
                ids = {x.id: new_id() for x in manifest.items}
                if len(ids) != len(manifest.items):
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

                store = BlobStore()

                def check_doc(value):
                    if value.get("format") == "native":
                        validate_content(value["content"])
                    if value.get("blob_key"):
                        key = value["blob_key"]
                        destination = store.path(key)
                        blob = archive.read("blobs/" + key)
                        if hashlib.sha256(blob).hexdigest() != key:
                            raise HTTPException(422, "附件校验失败")
                        if not destination.exists():
                            store.put(blob)
                            written_blobs.add(key)

                for x in manifest.items:
                    if x.kind not in allowed:
                        raise HTTPException(422, "不支持的内容类型")
                    value = rewrite(x.data)
                    if x.kind == "document":
                        check_doc(value)
                    if x.kind == "connector":
                        value.update(enabled=False, tools=[])
                    item = Item(
                        id=ids[x.id],
                        owner=user,
                        kind=x.kind,
                        title=x.title[:300],
                        project_id=ids.get(x.project_id),
                        parent_id=ids.get(x.parent_id),
                        revision=x.revision,
                        data=value,
                    )
                    s.add(item)
                for v in manifest.versions:
                    if v.document_id not in ids:
                        continue
                    value = rewrite(v.data)
                    check_doc(value)
                    s.add(
                        Version(
                            document_id=ids[v.document_id],
                            owner=user,
                            revision=v.revision,
                            data=value,
                        )
                    )
                return {
                    "restored": len(ids),
                    "message": "资料已恢复为新的副本，插件需要重新配置密钥和启用",
                }

            return receipt(
                s, user, idempotency_key, {"sha256": fingerprint}, apply
            )
    except Exception:
        for key in written_blobs:
            try:
                BlobStore().path(key).unlink(missing_ok=True)
            except OSError:
                pass
        raise
