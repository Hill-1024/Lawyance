"""
模块描述：大陆法系库对接冒烟用例，覆盖《Lawver 管辖库工作协调规范》§5 的验收清单。

在仓库根目录运行：

    .venv/Scripts/python -m RAG.civil_law.scripts.assembly_smoke_cases

退出码 0 = 全部通过；非 0 = 有用例失败。脚本只读检索，不修改语料。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from RAG.civil_law import (  # noqa: E402
    ensure_civil_law_database_ready,
    exact_search,
    fuzzy_search,
    link_search,
    reset_engine,
    semantic_search,
)
from RAG.civil_law.search import (  # noqa: E402
    build_manifest,
    can_incremental_rebuild,
    changed_source_paths,
)

CORE_FIELDS = ("law_name", "article_number", "content", "url")
EXTRA_FIELDS = ("source_id", "status", "effective_date", "language",
                "country", "country_label", "jurisdiction", "legal_system")

results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str) -> None:
    results.append((name, passed, detail))


def check_core_fields(hit: dict) -> str:
    missing = [field for field in CORE_FIELDS if field not in hit]
    if missing:
        return "缺少四核心字段: " + ", ".join(missing)
    empty = [field for field in CORE_FIELDS if field != "url" and not str(hit[field]).strip()]
    if empty:
        return "四核心字段为空: " + ", ".join(empty)
    return ""


def case_1_ensure() -> None:
    info = ensure_civil_law_database_ready()
    ok = isinstance(info, dict) and info.get("mode") in {"reuse", "full"}
    detail = json.dumps(info, ensure_ascii=False)[:220]
    record("1. ensure_civil_law_database_ready()", ok, detail)


def case_2_exact() -> None:
    # 三国的条号写法各测一条，验证 normalize_article_key 的跨语言归一化。
    samples = [
        ("Kitab Undang-Undang Hukum Perdata", "Pasal 1", "ID"),
        ("ประมวลกฎหมายแพ่งและพาณิชย์", "มาตรา 1", "TH"),
        ("Bộ luật Dân sự", "Điều 1", "VN"),
        # 印尼总统决定书用罗马数字条号
        ("Keputusan Presiden Nomor 10 Tahun 2023", "Pasal I", "ID"),
    ]
    ok = True
    notes = []
    for title, number, country in samples:
        payload = json.loads(exact_search(title, number))
        if not payload.get("success"):
            ok = False
            notes.append(f"{country} 未命中({payload.get('message')})")
            continue
        hit = payload.get("data") or {}
        problem = check_core_fields(hit)
        if problem:
            ok = False
            notes.append(f"{country} {problem}")
            continue
        if hit.get("country") != country:
            ok = False
            notes.append(f"{country} 国家码不符: {hit.get('country')}")
            continue
        if hit.get("jurisdiction") != hit.get("country_label"):
            ok = False
            notes.append(f"{country} jurisdiction 与 country_label 不一致")
            continue
        notes.append(f"{country} {hit['article_number']} url={'有' if hit['url'] else '空'}")
    record("2. exact_search 三国条号写法", ok, "; ".join(notes))


def case_3_alias_and_fuzzy() -> None:
    payload = json.loads(exact_search("印尼民法典", "第1条"))
    alias_ok = bool(payload.get("success"))
    alias_detail = "中文别名命中" if alias_ok else f"中文别名未命中({payload.get('message')})"

    fuzzy = json.loads(fuzzy_search("越南劳动法典 劳动合同 解除", limit=5))
    semantic = json.loads(semantic_search("越南劳动法典 劳动合同 解除", limit=5))
    fuzzy_ok = bool(fuzzy.get("data"))
    same = fuzzy.get("data") == semantic.get("data")

    ok = alias_ok and fuzzy_ok and same
    detail = (f"{alias_detail}; fuzzy 返回 {fuzzy.get('returned_count')} 条/"
              f"命中 {fuzzy.get('total_count')} 条; semantic 与 fuzzy 一致={same}")
    record("3. 中文别名 + fuzzy/semantic 等价", ok, detail)


def case_4_link() -> None:
    payload = json.loads(link_search("请说明印尼民法典第1条和泰国刑法典第1条分别怎么规定", limit=5))
    ok = bool(payload.get("success")) and bool(payload.get("references")) and bool(payload.get("text"))
    for reference in payload.get("references") or []:
        if not all(key in reference for key in ("title", "article_number", "url", "content")):
            ok = False
            break
    if "search_time" not in payload:
        ok = False
    detail = f"references={len(payload.get('references') or [])} text={'有' if payload.get('text') else '无'}"
    record("4. link_search 自然语言抽引用", ok, detail)


def case_5_country_filter() -> None:
    """本法系特有：三国混库必须能按国家隔离，否则会串出他国条文。"""
    payload = json.loads(fuzzy_search("越南 劳动合同 解除", limit=10))
    hits = payload.get("data") or []
    countries = {hit.get("country") for hit in hits}
    ok = bool(hits) and countries == {"VN"}
    detail = f"返回 {len(hits)} 条，国家集合={sorted(countries)}（应为 ['VN']）"

    payload_en = json.loads(fuzzy_search("indonesia perjanjian kerja", limit=10))
    hits_en = payload_en.get("data") or []
    countries_en = {hit.get("country") for hit in hits_en}
    ok = ok and bool(hits_en) and countries_en == {"ID"}
    detail += f"; 英文国名返回 {len(hits_en)} 条，国家集合={sorted(countries_en)}"
    record("5. 国家过滤（本法系特有）", ok, detail)


def case_6_usable_filter() -> None:
    """质检标记的不可用记录（OCR 页眉、假条号）不得进入检索结果。"""
    payload = json.loads(fuzzy_search("PRES IDEN REPUBLIK INDONESIA", limit=10))
    hits = payload.get("data") or []
    polluted = [hit for hit in hits if hit.get("article_number", "").startswith(("Điều 1", "Điều 2", "Điều 3"))
                and len(hit.get("content", "")) < 20]
    ok = not polluted
    record("6. usable=false 记录已隔离", ok, f"返回 {len(hits)} 条，可疑污染 {len(polluted)} 条")


def case_7_incremental_wiring() -> None:
    """增量重建接线的纯逻辑自检 —— 只比对清单，不改动任何语料。"""
    manifest = build_manifest()
    ok = can_incremental_rebuild(manifest)

    same_changed, same_removed = changed_source_paths(manifest, manifest)
    ok = ok and not same_changed and not same_removed

    # 伪造一份旧清单：首文件哈希不同（应判为 changed）、多出一个现已消失的文件（应判为 removed）
    files = dict(manifest["files"])
    first = sorted(files)[0]
    vanished = "thailand/crawl/__已删除的文件__.jsonl"
    doctored = dict(manifest)
    doctored["files"] = dict(files)
    doctored["files"][first] = {"size": files[first]["size"], "sha256": "x" * 64}
    doctored["files"][vanished] = {"size": 1, "sha256": "y" * 64}
    changed, removed = changed_source_paths(manifest, doctored)
    ok = ok and first in changed and vanished in removed

    detail = (f"can_incremental={can_incremental_rebuild(manifest)}; "
              f"同清单差异={len(same_changed)}/{len(same_removed)}; "
              f"伪造变更识别 changed={len(changed)} removed={len(removed)}")
    record("7. 增量重建接线（本法系特有）", ok, detail)


def main() -> int:
    reset_engine()
    case_1_ensure()
    case_2_exact()
    case_3_alias_and_fuzzy()
    case_4_link()
    case_5_country_filter()
    case_6_usable_filter()
    case_7_incremental_wiring()

    print("=" * 72)
    print("大陆法系库对接冒烟用例")
    print("=" * 72)
    failed = 0
    for name, passed, detail in results:
        mark = "PASS" if passed else "FAIL"
        if not passed:
            failed += 1
        print(f"[{mark}] {name}")
        print(f"        {detail}")
    print("-" * 72)
    print(f"合计 {len(results)} 项，通过 {len(results) - failed} 项，失败 {failed} 项")
    print("ALL_PASS" if failed == 0 else "HAS_FAILURE")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
