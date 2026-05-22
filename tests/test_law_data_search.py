"""
模块描述：本地法律数据库检索加固回归测试。
"""

import contextlib
import json
import tempfile
import unittest
from pathlib import Path

import RAG.law_data_search as law_search


def write_law_json(path: Path, law_name: str, articles: dict[str, str]) -> None:
    path.write_text(
        json.dumps(
            {
                "law_name": law_name,
                "short_name": law_name.replace("中华人民共和国", ""),
                "url": f"https://example.test/{law_name}",
                "cli": f"CLI.{law_name}",
                "effectiveness": "现行有效",
                "publish_date": "2026-01-01",
                "implement_date": "2026-01-01",
                "articles": articles,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@contextlib.contextmanager
def isolated_law_corpus():
    original = (
        law_search.RAW_DATA_DIR,
        law_search.CACHE_DIR,
        law_search.DB_PATH,
        law_search.MANIFEST_PATH,
        law_search._ENGINE,
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data_dir = root / "data"
        cache_dir = root / "cache"
        law_dir = data_dir / "法律"
        law_dir.mkdir(parents=True)
        write_law_json(
            law_dir / "中华人民共和国测试法.json",
            "中华人民共和国测试法",
            {
                "第一条": "本法用于测试本地法律数据库检索。",
                "第二条": "检索系统不得把 LIKE 通配符当成法律名称。",
            },
        )

        law_search.RAW_DATA_DIR = data_dir
        law_search.CACHE_DIR = cache_dir
        law_search.DB_PATH = cache_dir / "law.db"
        law_search.MANIFEST_PATH = cache_dir / "manifest.json"
        law_search._ENGINE = None
        try:
            yield data_dir
        finally:
            (
                law_search.RAW_DATA_DIR,
                law_search.CACHE_DIR,
                law_search.DB_PATH,
                law_search.MANIFEST_PATH,
                law_search._ENGINE,
            ) = original


class LawDataSearchHardeningTests(unittest.TestCase):
    def test_exact_search_does_not_treat_like_wildcard_as_law_name(self):
        with isolated_law_corpus():
            wildcard = json.loads(law_search.law_exact_search("%", "第一条"))
            too_broad = json.loads(law_search.law_exact_search("法", "第一条"))
            normal = json.loads(law_search.law_exact_search("测试法", "第一条"))

        self.assertFalse(wildcard["success"])
        self.assertIn("未找到法律", wildcard["message"])
        self.assertFalse(too_broad["success"])
        self.assertIn("未找到法律", too_broad["message"])
        self.assertTrue(normal["success"])
        self.assertEqual(normal["data"]["law_name"], "中华人民共和国测试法")

    def test_source_manifest_changes_when_file_content_changes(self):
        with isolated_law_corpus() as data_dir:
            source_file = data_dir / "法律" / "中华人民共和国测试法.json"
            first = law_search.build_source_manifest()
            payload = json.loads(source_file.read_text(encoding="utf-8"))
            payload["articles"]["第三条"] = "内容变更。"
            source_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            second = law_search.build_source_manifest()

        self.assertNotEqual(first["content_sha256"], second["content_sha256"])
        self.assertNotEqual(first, second)

    def test_incremental_rebuild_adds_changed_and_removed_json_sources(self):
        with isolated_law_corpus() as data_dir:
            first_status = law_search.ensure_law_database_ready(force_rebuild=True)
            self.assertEqual(first_status["mode"], "full")

            added_file = data_dir / "法律" / "中华人民共和国新增法.json"
            write_law_json(
                added_file,
                "中华人民共和国新增法",
                {"第一条": "新增法条会被增量写入本地 SQLite。"},
            )

            add_status = law_search.ensure_law_database_ready()
            added = json.loads(law_search.law_exact_search("新增法", "第一条"))

            self.assertEqual(add_status["mode"], "incremental")
            self.assertEqual(add_status["changed_files"], 1)
            self.assertEqual(add_status["indexed_laws"], 1)
            self.assertTrue(added["success"])
            self.assertIn("增量写入", added["data"]["content"])

            payload = json.loads(added_file.read_text(encoding="utf-8"))
            payload["articles"]["第二条"] = "变更后的同一文件也会被增量更新。"
            added_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            update_status = law_search.ensure_law_database_ready()
            updated = json.loads(law_search.law_exact_search("新增法", "第二条"))

            self.assertEqual(update_status["mode"], "incremental")
            self.assertEqual(update_status["changed_files"], 1)
            self.assertEqual(update_status["deleted_laws"], 1)
            self.assertTrue(updated["success"])
            self.assertIn("增量更新", updated["data"]["content"])

            added_file.unlink()
            remove_status = law_search.ensure_law_database_ready()
            removed = json.loads(law_search.law_exact_search("新增法", "第一条"))

            self.assertEqual(remove_status["mode"], "incremental")
            self.assertEqual(remove_status["removed_files"], 1)
            self.assertEqual(remove_status["deleted_laws"], 1)
            self.assertFalse(removed["success"])

    def test_search_limit_is_clamped(self):
        self.assertEqual(law_search.normalize_limit(999), law_search.MAX_SEARCH_LIMIT)
        self.assertEqual(law_search.normalize_limit(-10), 1)
        self.assertEqual(law_search.normalize_limit("bad"), 5)


if __name__ == "__main__":
    unittest.main()
