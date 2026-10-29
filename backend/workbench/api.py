"""Authenticated v2 workbench API. Stable identities, optimistic writes, immutable context."""

from __future__ import annotations
import asyncio
import base64
import copy
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    UploadFile,
    File,
    Form,
    Header,
    Request,
)
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import and_, or_, select
from services.auth_dependencies import get_current_user
from infra import database
from billing import ledger as billing
from workbench.store import (
    Item,
    Version,
    Receipt,
    Event,
    BlobStore,
    transaction,
    get_item,
    public,
    check_revision,
    now,
    new_id,
    revoke_conversation_shares,
)
from workbench.documents import (
    native,
    validate_content,
    text_of,
    extract,
    save_version,
    update_content,
    replace_text,
    export_docx,
    MAX_UPLOAD,
)
from workbench.skills import builtins
from workbench import connectors

router = APIRouter(prefix="/api/workbench", tags=["workbench"])
KINDS = {
    "projects": "project",
    "courts": "court",
    "conversations": "conversation",
    "documents": "document",
    "skills": "skill",
    "connectors": "connector",
}


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Create(Body):
    desc: str = Field(default="", max_length=2000)
    title: str = Field(min_length=1, max_length=300)
    project_id: str | None = None
    parent_id: str | None = None
    content: dict | None = None
    instructions: str = Field(default="", max_length=30000)
    url: str = Field(default="", max_length=2000)
    secret: str | None = Field(default=None, max_length=4096)


class Edit(Body):
    desc: str | None = Field(default=None, max_length=2000)
    expected_revision: int
    title: str | None = Field(default=None, min_length=1, max_length=300)
    project_id: str | None = None
    archived: bool | None = None
    favorite: bool | None = None
    enabled: bool | None = None
    published: bool | None = None
    instructions: str | None = Field(default=None, max_length=30000)
    secret: str | None = Field(default=None, max_length=4096)


class Save(Body):
    expected_revision: int
    content: dict


class Revision(Body):
    expected_revision: int


class Reference(Body):
    kind: Literal["document", "selection", "region", "folder", "skill", "connector"]
    id: str = Field(max_length=100)
    revision: int | None = None
    text: str | None = Field(default=None, max_length=30000)
    anchor: dict | None = None
    page: int | None = Field(default=None, ge=1, le=1000)
    rect: list[float] | None = Field(default=None, min_length=4, max_length=4)
    rotation: Literal[0, 90, 180, 270] = 0
    tools: list[str] = Field(default_factory=list, max_length=100)


class RunInput(Body):
    conversation_id: str
    message: str = Field(min_length=1, max_length=100000)
    references: list[Reference] = Field(default_factory=list, max_length=50)
    mode: Literal["default", "plan_and_solve"] = "default"
    use_ocp: bool = True


class Decision(Revision):
    action: Literal["accept", "reject"]


class Restore(Revision):
    revision: int


class Branch(Body):
    message_id: str
    title: str = Field(default="会话分支", max_length=300)


class Suggest(Body):
    project_id: str | None = None
    refresh: bool = False
    # 界面语言（BCP-47，如 en-US / zh-CN）：只影响生成提示，缺省中文、行为不变。
    locale: str | None = None


def enabled(user):
    """是否对该账号开放工作台。

    库是否可用的判断与 infra.database 走同一处（测试模式下派生 sqlite 也算可用）——
    这里只看 LAWVER_DATABASE_URL 的话，用仓库给的启动命令起的演示实例会出现
    「账号能登录、工作台全 403」的半可用状态。
    """
    if not database.cloud_database_ready():
        return False
    allowed = [name.strip() for name in os.environ.get("LAWVER_WORKBENCH_USERS", "").split(",") if name.strip()]
    if not allowed:
        # 空名单只在测试模式（显式开关 + 派生库）下放行全部账号；生产必须显式给名单。
        return database.derived_test_database()
    return "*" in allowed or user in allowed


def gate(request: Request, user=Depends(get_current_user)):
    if not enabled(user):
        raise HTTPException(403, "此账号尚未启用云端工作台")
    if (
        os.environ.get("LAWVER_WORKBENCH_READ_ONLY") == "1"
        and request.method not in ("GET", "HEAD")
        and not request.url.path.endswith("/stop")
    ):
        raise HTTPException(503, "工作台维护中，可继续读取和导出资料")
    return user


def receipt(session, user, key, payload, action):
    if not key or len(key) > 128:
        raise HTTPException(422, "需要有效的 Idempotency-Key")
    identifier = hashlib.sha256((user + ":" + key).encode()).hexdigest()
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    # PostgreSQL transaction lock also serializes identical first submissions.
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy import text

        session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": int(identifier[:15], 16)},
        )
    saved = session.get(Receipt, identifier)
    if saved:
        if saved.fingerprint != fingerprint:
            raise HTTPException(409, "幂等键已经用于不同请求")
        return saved.result
    result = action()
    session.add(
        Receipt(id=identifier, owner=user, fingerprint=fingerprint, result=result)
    )
    return result


def _require_key(key: str | None) -> None:
    """路由级幂等键预检：让昂贵的解析（附件、压缩包）发生之前就拒绝无键请求。

    完整校验仍由事务内的 receipt() 负责，这里只是提前短路。
    """
    if not key or len(key) > 128:
        raise HTTPException(422, "需要有效的 Idempotency-Key")


def _reachable_projects(session, user, rows):
    """列表/搜索的批量项目可达性复核。

    get_item 对一行内容的额外判定只有一条：带 project_id 的条目要求所属项目
    存在、归属本人且未删除（条目本身的 owner/kind/deleted_at 已由列表查询
    过滤）。这里一次查出相关 project 集合代替逐行 get_item：2000 行的列表
    从 2000 次查询降为 1 次，判定语义与 get_item 完全一致。
    """
    identifiers = {row.project_id for row in rows if row.project_id}
    if not identifiers:
        return set()
    return set(
        session.scalars(
            select(Item.id).where(
                Item.id.in_(identifiers),
                Item.owner == user,
                Item.deleted_at.is_(None),
            )
        )
    )


def _exclude_archived(query, user, kind):
    """归档 = 从常规列表里移出，但随时可在「已归档」恢复（不同于移入回收站）。

    条目自身的 archived_at 判一次；项目/会话/文件另外排除「所属项目已归档」的条目，
    否则归档项目后，其内容仍会从个人空间的会话/文件列表里漏出来。
    """
    kinds = {kind} if isinstance(kind, str) else set(kind)
    query = query.where(Item.archived_at.is_(None))
    if kinds & {"conversation", "document", "court"}:
        archived_projects = select(Item.id).where(
            Item.owner == user,
            Item.kind == "project",
            Item.archived_at.is_not(None),
            Item.deleted_at.is_(None),
        )
        query = query.where(
            or_(Item.project_id.is_(None), Item.project_id.not_in(archived_projects))
        )
    return query


def _encode_cursor(item) -> str:
    """不透明游标 = 最后一行 (updated_at, id) 的 base64（urlsafe，客户端原样回传）。"""
    raw = f"{item.updated_at.isoformat()}|{item.id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _decode_cursor(cursor: str):
    try:
        moment, identifier = base64.urlsafe_b64decode(cursor.encode()).decode().split(
            "|", 1
        )
        return datetime.fromisoformat(moment), identifier
    except Exception:
        raise HTTPException(422, "无效的游标")


def _after_cursor(query, cursor: str):
    """keyset 条件：排序是 updated_at DESC，下一页 = (updated_at, id) 严格小于游标。

    id 升一维防止同一时刻的并列行在翻页时丢行或重行。
    """
    moment, identifier = _decode_cursor(cursor)
    return query.where(
        or_(
            Item.updated_at < moment,
            and_(Item.updated_at == moment, Item.id < identifier),
        )
    )


def _page_envelope(rows, values, page: int):
    """信封形状：next_cursor 为空串表示没有更多。"""
    return {
        "items": values,
        "next_cursor": _encode_cursor(rows[-1]) if len(rows) == page else "",
    }


def _unique_document_title(session, user, project_id, title: str) -> str:
    """同名文件自动加序号（name (2).ext）。

    静默创建两条标题完全相同的记录，会让引用选择、搜索和清理都分不出彼此；
    破坏性方案（覆盖、拒绝）对已经上传完成的文件风险更大，所以取加序号。
    """

    def taken(candidate: str) -> bool:
        query = select(Item.id).where(
            Item.owner == user,
            Item.kind == "document",
            Item.title == candidate,
            Item.deleted_at.is_(None),
        )
        query = (
            query.where(Item.project_id == project_id)
            if project_id
            else query.where(Item.project_id.is_(None))
        )
        return session.scalar(query.limit(1)) is not None

    if not taken(title):
        return title
    stem, suffix = os.path.splitext(title)
    for index in range(2, 100):
        candidate = f"{stem} ({index}){suffix}"
        if not taken(candidate):
            return candidate
    return f"{stem} ({new_id()[:4]}){suffix}"


def create_document(session, user, project_id, title, content):
    validate_content(content)
    item = Item(
        id=new_id(),
        owner=user,
        kind="document",
        project_id=project_id,
        title=title,
        revision=1,
        data={"format": "native", "content": content},
        searchable=text_of(content),
    )
    session.add(item)
    session.flush()
    save_version(session, item)
    return item


@router.get("/status")
def status(user=Depends(get_current_user)):
    return {
        "enabled": enabled(user),
        "username": user,
        "configured": database.cloud_database_ready(),
    }


@router.get("/search")
def search(
    q: str = "",
    kind: str | None = None,
    space: str | None = None,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    user=Depends(gate),
):
    q = q.strip()[:200]
    kinds = ["project", "conversation", "document"]
    if kind:
        if kind not in kinds:
            raise HTTPException(422, "不支持的搜索类型")
        kinds = [kind]
    # 破坏性切换：恒返回 {items, next_cursor} 信封，缺省 limit=50（越界由 Query 校验 422）。
    with transaction() as s:
        query = select(Item).where(
            Item.owner == user,
            Item.deleted_at.is_(None),
            Item.kind.in_(kinds),
            or_(
                Item.title.icontains(q, autoescape=True),
                Item.searchable.icontains(q, autoescape=True),
            ),
        )
        if not include_archived:
            query = _exclude_archived(query, user, kinds)
        if space == "personal":
            query = query.where(Item.project_id.is_(None))
        elif space:
            get_item(s, user, space, "project")
            query = query.where(Item.project_id == space)
        page = limit
        if cursor is not None:
            query = _after_cursor(query, cursor)
        rows = s.scalars(query.order_by(Item.updated_at.desc()).limit(page)).all()
        reachable = _reachable_projects(s, user, rows)
        result = []
        for item in rows:
            if item.project_id and item.project_id not in reachable:
                continue
            value = {**public(item)}
            if item.kind == "document":
                value["data"] = {
                    key: field
                    for key, field in value["data"].items()
                    if key not in ("content", "text", "import_content")
                }
            result.append(
                {
                    **value,
                    "excerpt": item.searchable[
                        max(0, item.searchable.lower().find(q.lower()) - 40) :
                    ][:200],
                }
            )
        return _page_envelope(rows, result, page)


@router.post("/suggestions")
async def suggestions(body: Suggest, user=Depends(gate)):
    """首页建议只读素材标题；模型失败或维护期都不影响其它接口。"""
    # 幂等键豁免：查询类端点（读素材 + 进程内缓存），不产生持久变更，重放无副作用。
    if body.project_id:

        def check_project():
            with transaction() as s:
                get_item(s, user, body.project_id, "project")

        # async 端点里的事务一律进线程：同步查库会卡住同一事件循环上的 SSE 与 worker。
        await asyncio.to_thread(check_project)
    from workbench.suggestions import generate

    return await generate(user, body.project_id, body.refresh, body.locale)


@router.get("/trash")
def trash(user=Depends(gate)):
    with transaction() as s:
        return [
            public(x)
            for x in s.scalars(
                select(Item)
                .where(Item.owner == user, Item.deleted_at.is_not(None))
                .order_by(Item.deleted_at.desc())
                .limit(500)
            )
        ]


@router.get("/archived")
def archived(
    kind: str | None = None,
    limit: int = Query(default=200, ge=1, le=200),
    cursor: str | None = Query(default=None),
    user=Depends(gate),
):
    """已归档内容：独立于回收站，列表里看不到但可以逐条取消归档。

    不能复用前端内存里的索引：归档条目会被常规分页排除，旧会话可能早已不在第一页。
    设置页只关心会话，用 kind=conversation 过滤；project_title 供副标题显示归属。
    """
    if kind is not None and kind not in ("project", "conversation", "document"):
        raise HTTPException(422, "不支持的归档类型")
    with transaction() as s:
        query = select(Item).where(
            Item.owner == user,
            Item.deleted_at.is_(None),
            Item.archived_at.is_not(None),
            Item.kind == kind
            if kind
            else Item.kind.in_(("project", "conversation", "document")),
        )
        page = limit
        if cursor is not None:
            query = _after_cursor(query, cursor)
        rows = s.scalars(query.order_by(Item.updated_at.desc()).limit(page)).all()
        reachable = _reachable_projects(s, user, rows)
        # 所属项目名和条目同批取：设置页副标题要显示会话属于哪个项目，
        # 项目本身可能也已归档，不能依赖常规 /projects 列表。
        project_ids = {item.project_id for item in rows if item.project_id}
        project_titles = (
            dict(
                s.execute(
                    select(Item.id, Item.title).where(
                        Item.owner == user,
                        Item.id.in_(project_ids),
                        Item.deleted_at.is_(None),
                    )
                ).all()
            )
            if project_ids
            else {}
        )
        values = []
        for item in rows:
            if item.project_id and item.project_id not in reachable:
                continue
            value = public(item)
            value["project_title"] = project_titles.get(item.project_id)
            if item.kind == "conversation":
                value["data"] = {
                    k: v
                    for k, v in value["data"].items()
                    if k not in ("messages", "history")
                }
            if item.kind == "document":
                value["data"] = {
                    k: v
                    for k, v in value["data"].items()
                    if k not in ("content", "text", "import_content")
                }
            values.append(value)
        return _page_envelope(rows, values, page)


@router.post("/trash/{identifier}/restore")
def undelete(
    identifier: str,
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    # 恢复是创建/恢复类变更：强制幂等键，重试不会恢复出第二条记录。
    with transaction() as s:

        def apply():
            item = get_item(s, user, identifier, deleted=True, lock=True)
            if item.project_id:
                get_item(s, user, item.project_id, "project")
            item.deleted_at = None
            item.updated_at = now()
            return public(item)

        return receipt(s, user, idempotency_key, {"id": identifier}, apply)


@router.get("/documents/{identifier}/versions")
def versions(identifier: str, user=Depends(gate)):
    with transaction() as s:
        get_item(s, user, identifier, "document")
        return [
            {"revision": v.revision, "created_at": v.created_at.isoformat()}
            for v in s.scalars(
                select(Version)
                .where(Version.document_id == identifier, Version.owner == user)
                .order_by(Version.revision.desc())
            )
        ]


@router.get("/documents/{identifier}/versions/{revision}")
def version(identifier: str, revision: int, user=Depends(gate)):
    with transaction() as s:
        get_item(s, user, identifier, "document")
        v = s.scalar(
            select(Version).where(
                Version.document_id == identifier,
                Version.owner == user,
                Version.revision == revision,
            )
        )
        if not v:
            raise HTTPException(404, "版本不存在")
        return {
            "revision": v.revision,
            "data": {k: x for k, x in v.data.items() if k != "blob_key"},
        }


@router.put("/documents/{identifier}/content")
def save(identifier: str, body: Save, user=Depends(gate)):
    with transaction() as s:
        item = get_item(s, user, identifier, "document", lock=True)
        check_revision(item, body.expected_revision)
        if item.data.get("format") != "native":
            raise HTTPException(409, "请先创建编辑副本")
        update_content(s, item, body.content)
        return public(item)


@router.post("/documents/{identifier}/restore-version")
def restore_version(
    identifier: str,
    body: Restore,
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    # 恢复历史版本是创建/恢复类变更：强制幂等键，网络重试不会叠加出多个新版本。
    with transaction() as s:

        def apply():
            item = get_item(s, user, identifier, "document", lock=True)
            check_revision(item, body.expected_revision)
            v = s.scalar(
                select(Version).where(
                    Version.document_id == identifier,
                    Version.owner == user,
                    Version.revision == body.revision,
                )
            )
            if not v or v.data.get("format") != "native":
                raise HTTPException(422, "此版本不能恢复为原生文档")
            update_content(s, item, copy.deepcopy(v.data["content"]))
            return public(item)

        return receipt(
            s, user, idempotency_key, {"id": identifier, **body.model_dump()}, apply
        )


@router.post("/documents/upload")
async def upload(
    file: UploadFile = File(...),
    project_id: str | None = Form(None),
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    # 路由级预检：键缺失/超长直接 422，不要白解析一份 32 MB 的附件。
    _require_key(idempotency_key)
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "文件不能超过 32 MB")
    title = Path(file.filename or "附件").name[:300]
    data = await asyncio.to_thread(extract, raw, title)
    mime = file.content_type or "application/octet-stream"

    def store():
        # 落 blob（最大 32 MB）与建条目同样是阻塞操作，和解析一起放进线程。
        with transaction() as s:

            def apply():
                if project_id:
                    get_item(s, user, project_id, "project")
                # 同名文件自动加序号：此前两次上传同名文件会产生两条标题完全相同的记录，
                # 引用、搜索和清理时都分不出彼此。
                unique_title = _unique_document_title(s, user, project_id, title)
                data.update(blob_key=BlobStore().put(raw), size=len(raw), mime=mime)
                item = Item(
                    id=new_id(),
                    owner=user,
                    kind="document",
                    project_id=project_id,
                    title=unique_title,
                    revision=1,
                    data=data,
                    searchable=data.get("text", ""),
                )
                s.add(item)
                s.flush()
                save_version(s, item)
                return public(item)

            # 指纹取语义字段：同名同大小的文件传到不同项目算不同请求。
            return receipt(
                s,
                user,
                idempotency_key,
                {"filename": title, "size": len(raw), "project_id": project_id},
                apply,
            )

    return await asyncio.to_thread(store)


@router.get("/documents/{identifier}/blob")
def blob(identifier: str, user=Depends(gate)):
    with transaction() as s:
        item = get_item(s, user, identifier, "document")
        if not item.data.get("blob_key"):
            raise HTTPException(404, "没有原始文件")
        path = BlobStore().path(item.data["blob_key"])
        if not path.exists():
            raise HTTPException(410, "原始文件缺失，请联系管理员恢复备份")
        return FileResponse(
            path,
            media_type=item.data.get("mime", "application/octet-stream"),
            filename=item.title,
        )


@router.post("/documents/{identifier}/editable-copy")
def editable(
    identifier: str,
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    # 创建编辑副本是创建类变更：强制幂等键，重试不会复制出多份副本。
    with transaction() as s:

        def apply():
            item = get_item(s, user, identifier, "document")
            content = (
                item.data.get("content")
                or item.data.get("import_content")
                or native(item.data.get("text", ""))
            )
            copy_item = create_document(
                s, user, item.project_id, item.title + " · 编辑副本", content
            )
            copy_item.data = {
                **copy_item.data,
                "source_id": item.id,
                "conversion_notice": "这是编辑副本，复杂版式、批注、页眉页脚和嵌入对象可能未保留。原文件保持不变。",
            }
            return public(copy_item)

        return receipt(s, user, idempotency_key, {"id": identifier}, apply)


@router.get("/documents/{identifier}/export")
def export(identifier: str, user=Depends(gate)):
    from urllib.parse import quote

    with transaction() as s:
        item = get_item(s, user, identifier, "document")
        if item.data.get("format") != "native":
            raise HTTPException(422, "请下载原件或先创建编辑副本")
        raw = export_docx(item.data["content"])
        return Response(
            raw,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": "attachment; filename*=UTF-8''"
                + quote(item.title + ".docx")
            },
        )


@router.get("/change-proposals")
def proposals(document_id: str, user=Depends(gate)):
    with transaction() as s:
        get_item(s, user, document_id, "document")
        return [
            public(x)
            for x in s.scalars(
                select(Item)
                .where(
                    Item.owner == user,
                    Item.kind == "proposal",
                    Item.parent_id == document_id,
                )
                .order_by(Item.created_at.desc())
            )
        ]


@router.post("/change-proposals/{identifier}/decision")
def decide(
    identifier: str,
    body: Decision,
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    with transaction() as s:

        def apply():
            p = get_item(s, user, identifier, "proposal", lock=True)
            if p.data["status"] != "pending":
                raise HTTPException(409, "此建议已处理")
            doc = get_item(s, user, p.parent_id, "document", lock=True)
            if body.action == "accept":
                check_revision(doc, body.expected_revision)
                if doc.revision != p.data["base_revision"]:
                    raise HTTPException(
                        409,
                        {
                            "message": "建议基于旧版本，请重新生成或人工处理",
                            "current": public(doc),
                        },
                    )
                content = replace_text(
                    doc.data["content"], p.data["before"], p.data["after"]
                )
                update_content(s, doc, content)
                # Disjoint siblings from the same review remain applicable after a partial acceptance.
                for sibling in s.scalars(
                    select(Item)
                    .where(
                        Item.kind == "proposal",
                        Item.parent_id == doc.id,
                        Item.owner == user,
                    )
                    .with_for_update()
                ):
                    if (
                        sibling.id != p.id
                        and sibling.data.get("status") == "pending"
                        and sibling.data.get("base_revision") == body.expected_revision
                        and text_of(content).count(sibling.data.get("before", "")) == 1
                    ):
                        sibling.data = {**sibling.data, "base_revision": doc.revision}
            p.data = {
                **p.data,
                "status": "accepted" if body.action == "accept" else "rejected",
                "resolved_revision": doc.revision,
            }
            p.updated_at = now()
            return {"proposal": public(p), "document": public(doc)}

        return receipt(
            s, user, idempotency_key, {"id": identifier, **body.model_dump()}, apply
        )


@router.post("/conversations/{identifier}/branch")
def branch(
    identifier: str,
    body: Branch,
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    # 创建分支是创建类变更：强制幂等键，重试不会分支出第二条会话。
    with transaction() as s:

        def apply():
            original = get_item(s, user, identifier, "conversation")
            messages = original.data.get("messages", [])
            index = next(
                (i for i, m in enumerate(messages) if m["id"] == body.message_id), -1
            )
            if index < 0:
                raise HTTPException(404, "分支点不存在")
            item = Item(
                id=new_id(),
                owner=user,
                kind="conversation",
                title=body.title,
                project_id=original.project_id,
                parent_id=identifier,
                data={
                    "messages": copy.deepcopy(messages[: index + 1]),
                    "branch_point_message_id": body.message_id,
                },
            )
            s.add(item)
            s.flush()
            return public(item)

        return receipt(
            s, user, idempotency_key, {"id": identifier, **body.model_dump()}, apply
        )


@router.get("/conversations/{identifier}/export")
def export_conversation(identifier: str, user=Depends(gate)):
    """导出当前普通会话为 Word：认证与取数在这里，排版在 conversation_export。

    只导出该会话自己持有的消息快照（含分支继承的前缀），不递归父会话、
    不混入兄弟分支，也不导出 trace 内部历史与工具事件。
    """
    from urllib.parse import quote

    from workbench.conversation_export import (
        build_conversation_docx,
        formal_messages,
        safe_filename,
    )

    # 快照后立即收尾事务：DOCX 生成是纯内存计算，不占数据库会话。
    with transaction() as s:
        item = get_item(s, user, identifier, "conversation")
        for run in s.scalars(
            select(Item).where(
                Item.owner == user,
                Item.kind == "run",
                Item.parent_id == identifier,
                Item.deleted_at.is_(None),
            )
        ):
            if run.data.get("status") in ("queued", "running", "waiting_confirmation", "waiting_user"):
                raise HTTPException(409, "会话正在运行任务，请等待完成后再导出")
        title = item.title
        messages = [
            {
                "role": message.get("role"),
                "content": message.get("content"),
                "created_at": message.get("created_at"),
            }
            for message in item.data.get("messages", [])
        ]
    formal = formal_messages(messages)
    if not formal:
        raise HTTPException(422, "会话还没有可导出的消息")
    raw = build_conversation_docx(title, formal)
    return Response(
        raw,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            # quote 转义非 ASCII 与 CR/LF：中文文件名可用，也无响应头注入空间。
            "Content-Disposition": "attachment; filename=\"conversation.docx\"; "
            "filename*=UTF-8''" + quote(safe_filename(title) + ".docx"),
            "Cache-Control": "no-store",
        },
    )


@router.post("/connectors/{identifier}/test")
async def test_connector(identifier: str, user=Depends(gate)):
    # 幂等键豁免：连接探测只回写测试时间/工具清单，不创建内容；要求带键反而挡住「再测一次」。
    # 三段事务都进线程执行；中间的远程调用本身是 async 的，不占线程。
    def load():
        with transaction() as s:
            return copy.deepcopy(get_item(s, user, identifier, "connector").data)

    def record(**values):
        with transaction() as s:
            item = get_item(s, user, identifier, "connector", lock=True)
            item.data = {**item.data, **values}
            return public(item)

    data = await asyncio.to_thread(load)
    try:
        catalog = await connectors.invoke(data)
    except Exception:
        await asyncio.to_thread(
            record, last_error="连接失败，请检查公网 HTTPS 地址、密钥和服务状态。"
        )
        raise HTTPException(502, "插件连接失败：检查地址、密钥或服务状态")
    return await asyncio.to_thread(
        record, tools=catalog, last_error=None, tested_at=now().isoformat()
    )


def freeze_refs(s, user, project_id, refs):
    frozen = []
    for ref in refs:
        if ref.kind == "skill" and ref.id.startswith("builtin-"):
            item = next((x for x in builtins() if x["id"] == ref.id), None)
            if not item:
                raise HTTPException(404, "技能不存在")
            frozen.append(
                {
                    **ref.model_dump(),
                    "title": item["title"],
                    "revision": 1,
                    "instructions": item["data"]["instructions"],
                }
            )
            continue
        kind = {"selection": "document", "region": "document", "folder": "project"}.get(
            ref.kind, ref.kind
        )
        item = get_item(s, user, ref.id, kind)
        if (
            kind in ("document", "project")
            and (item.project_id if kind == "document" else item.id) != project_id
        ):
            raise HTTPException(403, "材料必须属于本次会话的项目")
        if ref.kind == "folder":
            docs = s.scalars(
                select(Item).where(
                    Item.owner == user,
                    Item.kind == "document",
                    Item.project_id == item.id,
                    Item.deleted_at.is_(None),
                    # 归档文件从常规项目引用里移出；要引用单份归档文件仍可按 id 显式选择。
                    Item.archived_at.is_(None),
                )
            ).all()
            if len(docs) > 100:
                raise HTTPException(422, "项目超过 100 份文件，请选择具体文件")
            frozen.extend(
                freeze_refs(
                    s,
                    user,
                    project_id,
                    [
                        Reference(kind="document", id=d.id, revision=d.revision)
                        for d in docs
                    ],
                )
            )
            continue
        if ref.revision is not None:
            check_revision(item, ref.revision)
        value = {**ref.model_dump(), "title": item.title, "revision": item.revision}
        if kind == "document":
            text = (
                text_of(item.data.get("content", {}))
                if item.data.get("format") == "native"
                else item.data.get("text", "")
            )
            if ref.kind == "selection" and (not ref.text or ref.text not in text):
                raise HTTPException(409, "选区已失效，请重新选择")
            if ref.kind == "region":
                if (
                    item.data.get("format") not in ("pdf", "image")
                    or not ref.page
                    or not ref.rect
                    or not all(0 <= v <= 1 for v in ref.rect)
                    or ref.rect[0] >= ref.rect[2]
                    or ref.rect[1] >= ref.rect[3]
                    or ref.page > item.data.get("pages", 1)
                ):
                    raise HTTPException(422, "无效页面选区")
            value["text"] = ref.text if ref.kind == "selection" else text[:100000]
        if kind == "skill":
            if not item.data.get("published") or not item.data.get("enabled", True):
                raise HTTPException(409, "技能尚未发布或已停用")
            value["instructions"] = item.data.get("instructions", "")
        if kind == "connector":
            if not item.data.get("enabled"):
                raise HTTPException(409, "插件未启用")
            catalog = {x["name"]: x for x in item.data.get("tools", [])}
            if not ref.tools or any(name not in catalog for name in ref.tools):
                raise HTTPException(422, "请选择本次可使用的插件工具")
            value["catalog"] = [catalog[name] for name in ref.tools]
        frozen.append(value)
    if len(json.dumps(frozen)) > 800000:
        raise HTTPException(422, "引用材料过多，请缩小范围")
    return frozen


def _append_run(
    session,
    user: str,
    conv: Item,
    *,
    message: str,
    references: list[dict],
    mode: str,
    use_ocp: bool,
) -> Item:
    """在会话末尾追加一条用户消息并创建一个排队 run。

    start_run 与 ask_user 作答接口共用：两条路径的消息、引用和搜索索引行为必须一致，
    否则「直接发消息」与「点选项续接」会在历史里长出两种不同形状。
    """
    run = Item(
        id=new_id(),
        owner=user,
        kind="run",
        parent_id=conv.id,
        project_id=conv.project_id,
        title=message[:80],
        data={
            "status": "queued",
            "message": message,
            "references": references,
            "mode": mode,
            "use_ocp": use_ocp,
        },
    )
    messages = [
        *conv.data.get("messages", []),
        {
            "id": new_id(),
            "role": "user",
            "content": message,
            "references": references,
            "run_id": run.id,
            "created_at": now().isoformat(),
        },
    ]
    conv.data = {**conv.data, "messages": messages}
    conv.updated_at = now()
    conv.searchable += "\n" + message
    session.add(run)
    session.flush()
    return run


@router.post("/runs")
def start_run(
    body: RunInput, idempotency_key: str | None = Header(None), user=Depends(gate)
):
    if os.environ.get("LAWVER_WORKBENCH_READ_ONLY") == "1":
        raise HTTPException(503, "云端暂处于只读维护状态")
    # 排队之前先看余额：没有 credits 就不该占住队列与模型资源。
    allowed, refusal = billing.can_spend(user)
    if not allowed:
        raise HTTPException(402, refusal)
    with transaction() as s:

        def apply():
            conv = get_item(s, user, body.conversation_id, "conversation", lock=True)
            for active in s.scalars(
                select(Item).where(
                    Item.owner == user, Item.kind == "run", Item.parent_id == conv.id
                )
            ):
                status = active.data.get("status")
                if status in ("queued", "running", "waiting_confirmation"):
                    raise HTTPException(409, "此会话已有运行中的任务")
                if status == "waiting_user":
                    # 熔断兜底：用户不点选项、直接发新消息时，旧提问自动作废，
                    # 新消息带着完整历史继续，不让会话卡在等待态。
                    choice = active.data.get("pending_choice") or {}
                    active.data = {
                        **active.data,
                        "status": "completed",
                        "pending_choice": {
                            **choice,
                            "answered": False,
                            "superseded": True,
                            "superseded_reason": "new_message",
                            "superseded_at": now().isoformat(),
                        },
                    }
                    active.updated_at = now()
            refs = freeze_refs(s, user, conv.project_id, body.references)
            run = _append_run(
                s,
                user,
                conv,
                message=body.message,
                references=refs,
                mode=body.mode,
                use_ocp=body.use_ocp,
            )
            return public(run)

        return receipt(s, user, idempotency_key, body.model_dump(), apply)


@router.get("/runs/{identifier}")
def get_run(identifier: str, user=Depends(gate)):
    with transaction() as s:
        return public(get_item(s, user, identifier, "run"))


@router.get("/runs/{identifier}/events")
def events(identifier: str, after: int = 0, user=Depends(gate)):
    with transaction() as s:
        run = get_item(s, user, identifier, "run")
        rows = s.scalars(
            select(Event)
            .where(Event.run_id == identifier, Event.seq > after)
            .order_by(Event.seq)
            .limit(300)
        ).all()
        return {
            "run": public(run),
            "has_more": len(rows) == 300,
            "events": [{"seq": x.seq, **x.payload} for x in rows],
        }


@router.post("/runs/{identifier}/stop")
def stop(identifier: str, user=Depends(gate)):
    # 幂等键豁免：紧急取消必须随手可用，重放 stop 也无副作用（只是置停止标记）。
    with transaction() as s:
        run = get_item(s, user, identifier, "run", lock=True)
        status = run.data["status"]
        if status == "waiting_user":
            # 等待选择不是执行中：停在这里时直接收尾，避免 run 永远挂在等待态。
            choice = run.data.get("pending_choice") or {}
            run.data = {
                **run.data,
                "status": "stopped",
                "pending_choice": {
                    **choice,
                    "answered": False,
                    "cancelled": True,
                    "cancelled_at": now().isoformat(),
                },
            }
            run.updated_at = now()
        elif status in ("queued", "running", "waiting_confirmation"):
            run.data = {**run.data, "stop_requested": True}
        return public(run)


class Approval(Body):
    call_id: str
    allow: bool


@router.post("/runs/{identifier}/confirmation")
def confirmation(
    identifier: str,
    body: Approval,
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    # 审批决定是变更类提交：强制幂等键，双击「允许/拒绝」不会写入两次。
    with transaction() as s:

        def apply():
            run = get_item(s, user, identifier, "run", lock=True)
            if (
                run.data.get("confirmation", {}).get("id") != body.call_id
                or run.data.get("status") != "waiting_confirmation"
            ):
                raise HTTPException(409, "确认请求已失效")
            run.data = {**run.data, "approval": body.model_dump()}
            return public(run)

        return receipt(
            s, user, idempotency_key, {"id": identifier, **body.model_dump()}, apply
        )


class ChoiceAnswer(Body):
    choice_id: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=10000)


@router.post("/runs/{identifier}/choice")
def answer_choice(
    identifier: str,
    body: ChoiceAnswer,
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    """把用户选择作为新的用户消息续接同一会话。

    ask_user 的 run 在 worker 侧已经结束（不占执行槽），因此作答不是“唤醒旧进程”，
    而是带着旧 run 的完整 trace 和引用发起下一个 run。旧 run 置 answered，
    选择卡片随之消失；断线后也能从 run.data.pending_choice 恢复。
    """
    allowed, refusal = billing.can_spend(user)
    if not allowed:
        raise HTTPException(402, refusal)
    with transaction() as s:

        def apply():
            # 先拿会话 id 再按 conv → run 的固定顺序加锁，避免与 start_run 交叉死锁。
            current = get_item(s, user, identifier, "run")
            conv = get_item(s, user, current.parent_id, "conversation", lock=True)
            run = get_item(s, user, identifier, "run", lock=True)
            choice = run.data.get("pending_choice") or {}
            answered_run_id = choice.get("answer_run_id")
            if answered_run_id:
                # 双击或网络重试：第一次作答已经创建了续接 run，直接返回同一个。
                return public(get_item(s, user, str(answered_run_id), "run"))
            if (
                run.data.get("status") != "waiting_user"
                or not choice
                or choice.get("id") != body.choice_id
            ):
                raise HTTPException(409, "选择请求已失效，请刷新会话后重试")
            new_run = _append_run(
                s,
                user,
                conv,
                message=body.value,
                references=copy.deepcopy(run.data.get("references") or []),
                mode=str(run.data.get("mode") or "default"),
                use_ocp=bool(run.data.get("use_ocp", True)),
            )
            run.data = {
                **run.data,
                "status": "completed",
                "pending_choice": {
                    **choice,
                    "answered": True,
                    "selected_value": body.value,
                    "answered_at": now().isoformat(),
                    "answer_run_id": new_run.id,
                },
            }
            run.updated_at = now()
            s.flush()
            return public(new_run)

        return receipt(
            s,
            user,
            idempotency_key,
            {"id": identifier, **body.model_dump()},
            apply,
        )


class CourtSnapshot(Body):
    expected_revision: int = Field(ge=0)
    project_id: str
    session: dict


@router.get("/projects/{identifier}/court-context")
def court_context(identifier: str, user=Depends(gate)):
    """Owner-scoped source snapshots, never court private briefs or tool memory."""
    with transaction() as s:
        project = get_item(s, user, identifier, "project")
        rows = s.scalars(select(Item).where(
            Item.owner == user, Item.kind == "conversation", Item.project_id == identifier,
            Item.deleted_at.is_(None), Item.archived_at.is_(None),
        ).order_by(Item.updated_at.desc())).all()
        sources, remaining, omitted = [], 40000, 0
        for row in rows:
            messages = [m for m in row.data.get("messages", []) if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
            content = "\n\n".join(("用户：" if m["role"] == "user" else "AI 草稿（待核验）：") + m["content"] for m in messages)
            if not content:
                continue
            if not remaining:
                omitted += 1
                continue
            excerpt = content[:min(10000, remaining)]
            remaining -= len(excerpt)
            sources.append({"id": row.id, "title": row.title, "revision": row.revision,
                            "updated_at": row.updated_at.isoformat(), "text": excerpt,
                            "truncated": len(excerpt) < len(content)})
        return {"project": {"id": project.id, "title": project.title, "desc": project.data.get("desc", "")},
                "sources": sources, "omitted": omitted}


@router.put("/courts/{identifier}/snapshot")
def save_court(identifier: str, body: CourtSnapshot, user=Depends(gate)):
    snapshot = copy.deepcopy(body.session)
    if (len(identifier) > 100 or snapshot.get("id") != identifier
            or snapshot.get("project_id") != body.project_id
            or snapshot.get("case_type") not in ("civil", "criminal", "administrative")
            or not isinstance(snapshot.get("title"), str)
            or len(snapshot["title"]) > 300
            or not all(isinstance(snapshot.get(k), dict) for k in ("shared_dossier", "private_brief", "court_state", "agent_states"))
            or not all(isinstance(snapshot.get(k), list) for k in ("public_events", "pending_interjections"))
            or len(json.dumps(snapshot, ensure_ascii=False)) > 2_000_000):
        raise HTTPException(422, "庭审记录格式无效或超过大小限制")
    # Loading a persisted session must not silently restart an agent operation.
    snapshot["auto_mode"] = False
    with transaction() as s:
        get_item(s, user, body.project_id, "project")
        existing = s.get(Item, identifier)
        if existing:
            item = get_item(s, user, identifier, "court", lock=True)
            if item.project_id != body.project_id:
                raise HTTPException(422, "庭审不能通过保存记录改变项目归属")
            if item.data.get("session") == snapshot:
                return public(item)
            check_revision(item, body.expected_revision)
            item.revision += 1
        else:
            if body.expected_revision != 0:
                raise HTTPException(409, "庭审记录已不存在，请保留本地副本")
            item = Item(id=identifier, kind="court", owner=user, project_id=body.project_id,
                        title=snapshot["title"], revision=1, data={})
            s.add(item)
        item.title = snapshot["title"]
        item.data = {"session": snapshot}
        item.updated_at = now()
        s.flush()
        return public(item)


# Generic resource routes are deliberately last (upload/search paths must win).
@router.get("/{family}")
def listing(
    family: str,
    project_id: str | None = None,
    include_session: bool = False,
    include_archived: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    user=Depends(gate),
):
    kind = KINDS.get(family)
    if not kind:
        raise HTTPException(404, "内容不存在或无权访问")
    # 破坏性切换：恒返回 {items, next_cursor} 信封，缺省 limit=50（越界由 Query 校验 422）。
    with transaction() as s:
        query = select(Item).where(
            Item.owner == user, Item.kind == kind, Item.deleted_at.is_(None)
        )
        if not include_archived:
            query = _exclude_archived(query, user, kind)
        if project_id:
            get_item(s, user, project_id, "project")
            query = query.where(Item.project_id == project_id)
        page = limit
        if cursor is not None:
            query = _after_cursor(query, cursor)
        rows = s.scalars(query.order_by(Item.updated_at.desc()).limit(page)).all()
        # 批量复核项目可达性（语义同 get_item）：每行一次查询的 N+1 在这里收口。
        reachable = _reachable_projects(s, user, rows)
        values = []
        for item in rows:
            if item.project_id and item.project_id not in reachable:
                continue
            value = public(item)
            if kind == "court" and not include_session:
                snapshot = item.data.get("session", {})
                value["data"] = {"case_type": snapshot.get("case_type"), "user_side": snapshot.get("user_side"), "phase": snapshot.get("court_state", {}).get("phase")}
            if kind == "conversation":
                value["data"] = {
                    k: v
                    for k, v in value["data"].items()
                    if k not in ("messages", "history")
                }
            if kind == "document":
                value["data"] = {
                    k: v
                    for k, v in value["data"].items()
                    if k not in ("content", "text", "import_content")
                }
            values.append(value)
        envelope = _page_envelope(rows, values, page)
        envelope["items"] = builtins() + envelope["items"] if kind == "skill" else envelope["items"]
        return envelope


@router.post("/{family}")
def create(
    family: str,
    body: Create,
    idempotency_key: str | None = Header(None),
    user=Depends(gate),
):
    kind = KINDS.get(family)
    if not kind:
        raise HTTPException(404, "内容不存在或无权访问")
    if kind == "court":
        raise HTTPException(422, "请使用庭审保存接口")
    with transaction() as s:

        def apply():
            if body.project_id:
                get_item(s, user, body.project_id, "project")
            if body.parent_id:
                raise HTTPException(422, "请使用分支接口创建关联会话")
            if kind == "document":
                return public(
                    create_document(
                        s, user, body.project_id, body.title, body.content or native()
                    )
                )
            data = {"desc": body.desc.strip()} if kind == "project" else {}
            if kind == "conversation":
                data = {"messages": []}
            if kind == "skill":
                data = {
                    "instructions": body.instructions,
                    "enabled": True,
                    "published": False,
                }
            if kind == "connector":
                data = {
                    "url": connectors.endpoint(body.url),
                    "encrypted_secret": connectors.encrypt(body.secret),
                    "enabled": False,
                    "tools": [],
                }
            item = Item(
                id=new_id(),
                owner=user,
                kind=kind,
                title=body.title,
                project_id=body.project_id if kind == "conversation" else None,
                data=data,
            )
            s.add(item)
            s.flush()
            return public(item)

        # 创建是创建/恢复类变更：幂等键一律强制（历史上是「带键才去重」的可选行为，
        # 已统一为方向 A——缺失或超长的键在 receipt 里直接 422）。
        return receipt(
            s, user, idempotency_key, {"family": family, **body.model_dump()}, apply
        )


@router.get("/{family}/{identifier}")
def detail(family: str, identifier: str, user=Depends(gate)):
    if family not in KINDS:
        raise HTTPException(404, "内容不存在或无权访问")
    with transaction() as s:
        return public(get_item(s, user, identifier, KINDS[family]))


@router.patch("/{family}/{identifier}")
def edit(family: str, identifier: str, body: Edit, user=Depends(gate)):
    if family not in KINDS:
        raise HTTPException(404, "内容不存在或无权访问")
    with transaction() as s:
        item = get_item(s, user, identifier, KINDS[family], lock=True)
        check_revision(item, body.expected_revision)
        fields = body.model_dump(exclude_unset=True)
        fields.pop("expected_revision")
        if "title" in fields:
            item.title = fields.pop("title")
        if "project_id" in fields:
            if item.kind not in ("document", "conversation"):
                raise HTTPException(422, "此内容不能移动")
            pid = fields.pop("project_id")
            if pid:
                get_item(s, user, pid, "project")
            item.project_id = pid
        if "archived" in fields:
            # 归档是显式的可见性开关：归档时间用于「已归档」排序，取消归档置空。
            archive = bool(fields.pop("archived"))
            if archive and item.kind in ("project", "conversation"):
                # 与移入回收站同一判定：归档会关掉会话标签，不能把正在跑的任务藏起来。
                query = select(Item).where(Item.owner == user, Item.kind == "run")
                query = (
                    query.where(Item.project_id == item.id)
                    if item.kind == "project"
                    else query.where(Item.parent_id == item.id)
                )
                if any(
                    run.data.get("status")
                    in ("queued", "running", "waiting_confirmation", "waiting_user")
                    for run in s.scalars(query)
                ):
                    raise HTTPException(409, "请先停止正在执行的任务")
            item.archived_at = now() if archive else None
            # 旧版本把标记写在 data 里；升级后以列为准，顺手清掉历史残留。
            item.data.pop("archived", None)
        allowed = {"favorite"} | (
            {"instructions", "published", "enabled"}
            if item.kind == "skill"
            else {"enabled", "secret"}
            if item.kind == "connector"
            else {"desc"}
            if item.kind == "project"
            else set()
        )
        if set(fields) - allowed:
            raise HTTPException(422, "不支持的设置")
        if "secret" in fields:
            fields["encrypted_secret"] = connectors.encrypt(fields.pop("secret"))
        item.data = {**item.data, **fields}
        item.revision += 1
        item.updated_at = now()
        if item.kind == "document":
            save_version(s, item)
        return public(item)


@router.delete("/{family}/{identifier}")
def delete(family: str, identifier: str, user=Depends(gate)):
    if family not in KINDS:
        raise HTTPException(404, "内容不存在或无权访问")
    with transaction() as s:
        item = get_item(s, user, identifier, KINDS[family], lock=True)
        if item.kind in ("project", "conversation"):
            query = select(Item).where(Item.owner == user, Item.kind == "run")
            query = (
                query.where(Item.project_id == identifier)
                if item.kind == "project"
                else query.where(Item.parent_id == identifier)
            )
            if any(
                r.data.get("status")
                in ("queued", "running", "waiting_confirmation", "waiting_user")
                for r in s.scalars(query)
            ):
                raise HTTPException(409, "请先停止项目内正在执行的任务")
        if item.kind == "conversation":
            revoke_conversation_shares(s, user, [item.id])
        elif item.kind == "project":
            revoke_conversation_shares(s, user, select(Item.id).where(
                Item.owner == user, Item.kind == "conversation", Item.project_id == item.id,
            ))
        item.deleted_at = now()
        return {"deleted": True, "retention_days": 30}
