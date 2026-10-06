"""
模块描述：工作台 worker 的生命周期回归——停止/报错时照样结算、心跳失败不留下脱管任务、
数据库写入不占用事件循环且被取消时先落库再传播取消（同一 run 的事件顺序不乱）。

这些用例只替换 worker 的数据库与计费边界，不连模型：要验证的是调度语义本身。
"""

import asyncio
import threading

import pytest

from workbench import store as workbench_store
from workbench import worker


def _fake_turn_body(record_tool=True, *, hang=False, error=None):
    async def body(_identifier, _user):
        from billing import metering

        if record_tool:
            metering.record_tool("web_search")
        if hang:
            await asyncio.sleep(3600)
        if error is not None:
            raise error

    return body


@pytest.fixture
def billing_boundary(monkeypatch):
    """计费边界换成内存记录：账号读取、建表与结算都不碰数据库。"""
    from billing import ledger
    from infra import account_store

    settled = []

    def fake_settle(turn, **_kwargs):
        settled.append(turn)
        return {"credits": 0.0}

    monkeypatch.setattr(account_store, "get_user", lambda _user: {"plan": "metered"})
    monkeypatch.setattr(ledger, "ensure_tables", lambda: None)
    monkeypatch.setattr(ledger, "settle", fake_settle)
    monkeypatch.setattr(worker, "emit", lambda *_args, **_kwargs: None)
    return settled


def test_execute_settles_usage_when_the_turn_fails(billing_boundary, monkeypatch):
    monkeypatch.setattr(worker, "_execute_turn", _fake_turn_body(error=RuntimeError("model failed")))

    with pytest.raises(RuntimeError):
        asyncio.run(worker.execute("run-error", "alice"))

    assert len(billing_boundary) == 1
    assert billing_boundary[0].ref_id == "run-error"
    assert billing_boundary[0].tool_calls == 1


def test_execute_settles_usage_when_the_run_is_stopped(billing_boundary, monkeypatch):
    monkeypatch.setattr(worker, "_execute_turn", _fake_turn_body(hang=True))

    async def stop_midway():
        task = asyncio.create_task(worker.execute("run-stop", "alice"))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(stop_midway())

    assert len(billing_boundary) == 1
    assert billing_boundary[0].ref_id == "run-stop"
    assert billing_boundary[0].tool_calls == 1


def test_offload_commits_before_propagating_cancellation():
    started, release = threading.Event(), threading.Event()
    finished = []

    def slow_write():
        started.set()
        release.wait(5)
        finished.append(True)

    async def scenario():
        task = asyncio.create_task(worker._offload(slow_write))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0.05)
        # 线程里的事务还没提交完：取消不能先一步生效，否则后写的事件会插到它前面。
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished == [True]

    asyncio.run(scenario())


def _record_writes(monkeypatch):
    writes = []
    monkeypatch.setattr(
        worker,
        "change_state",
        lambda identifier, **values: writes.append(("state", values, threading.get_ident())),
    )
    monkeypatch.setattr(
        worker,
        "emit",
        lambda run_id, payload: writes.append(("emit", payload, threading.get_ident())),
    )
    return writes


def test_supervise_stop_writes_state_in_order_and_off_the_event_loop(monkeypatch):
    writes = _record_writes(monkeypatch)
    cancelled = []

    async def long_run(_identifier, _user):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    monkeypatch.setattr(worker, "execute", long_run)
    monkeypatch.setattr(worker, "heartbeat", lambda _identifier, _user: True)

    loop_thread = []

    async def scenario():
        loop_thread.append(threading.get_ident())
        await worker.supervise("run-1", "alice")

    asyncio.run(scenario())

    assert cancelled == [True]
    assert [(kind, payload) for kind, payload, _ in writes] == [
        ("state", {"status": "stopped"}),
        ("emit", {"type": "done"}),
    ]
    assert all(thread != loop_thread[0] for _, _, thread in writes)


def test_supervise_cancels_the_run_when_the_heartbeat_fails(monkeypatch):
    writes = _record_writes(monkeypatch)
    cancelled = []

    async def long_run(_identifier, _user):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    def broken_heartbeat(_identifier, _user):
        raise RuntimeError("database went away")

    monkeypatch.setattr(worker, "execute", long_run)
    monkeypatch.setattr(worker, "heartbeat", broken_heartbeat)

    asyncio.run(worker.supervise("run-2", "alice"))

    # 任务本体必须被一并取消：脱管继续跑的话，结束时会把 failed 覆盖成 completed。
    assert cancelled == [True]
    assert writes[0][0] == "state" and writes[0][1]["status"] == "failed"
    assert writes[1][0] == "emit" and writes[1][1]["type"] == "error"


def test_loop_runs_users_concurrently_and_caps_each_account(monkeypatch):
    """loop 并发监管：一个用户的慢任务不堵其他用户，但单账号按套餐并行度受限。"""
    started = []
    cancelled_flags = []
    seen_exclusions = []

    jobs = iter([("run-a1", "alice"), ("run-b1", "bob"), ("run-a2", "alice"), None])

    def fake_claim(excluded=frozenset()):
        seen_exclusions.append(set(excluded))
        while True:
            try:
                job = next(jobs)
            except StopIteration:
                return None
            if job and job[1] in excluded:
                continue  # 并发已满的账号在查询里被过滤
            return job

    async def fake_supervise(identifier, _user):
        started.append(identifier)
        try:
            while True:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            cancelled_flags.append(identifier)
            raise

    def fake_parallel(_user):
        return 1  # 与真实实现一致：同步函数，由 loop 经 to_thread 调用

    monkeypatch.setattr(worker, "claim", fake_claim)
    monkeypatch.setattr(worker, "supervise", fake_supervise)
    monkeypatch.setattr(worker, "_parallel_tasks_for", fake_parallel)

    async def scenario():
        task = asyncio.create_task(worker.loop())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if len(started) >= 2:
                break
        # bob 的任务被认领：alice 的任务不再占住唯一执行槽。
        assert started == ["run-a1", "run-b1"], started
        # 第二次认领时 alice 已满（并行度 1），被排除在候选之外。
        assert "alice" in seen_exclusions[1], seen_exclusions
        # alice 的第二个排队任务没有被认领。
        assert "run-a2" not in started
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # 退出时在跑的监管任务要一并取消，不能脱管。
        assert sorted(cancelled_flags) == ["run-a1", "run-b1"], cancelled_flags

    asyncio.run(scenario())


def test_startup_self_healing_table_creation_does_not_race(tmp_path, monkeypatch):
    """冷启动时 worker 认领任务（建全部表）与账号引导（建账号表）在不同线程里同时建表。

    checkfirst 是先查后建：两边都查到没有、一起 CREATE，输的一方报 table already exists。
    SQLite 下 worker 会记一条「数据库不可用」再等 5 秒；PostgreSQL 下账号引导接不住
    ProgrammingError，启动直接失败。建表统一走 infra.database.create_tables 串行。
    """
    from infra import account_store, throttle

    monkeypatch.setenv("LAWVER_WORKBENCH_TESTING", "1")
    creators = (workbench_store.ensure_tables, account_store.ensure_tables, throttle.ensure_tables)
    for round_index in range(8):
        monkeypatch.setenv("LAWVER_DATABASE_URL", "sqlite:///" + str(tmp_path / f"cold-{round_index}.db"))
        barrier = threading.Barrier(len(creators))
        errors = []

        def create(fn):
            barrier.wait()
            try:
                fn()
            except Exception as exc:  # 修复前：OperationalError: table ... already exists
                errors.append(repr(exc)[:200])

        threads = [threading.Thread(target=create, args=(fn,)) for fn in creators]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == [], errors
