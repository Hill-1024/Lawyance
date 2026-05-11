"""
模块描述：本地法律数据库检索加固回归测试。
"""

import contextlib
import json
import tempfile
import unittest
from pathlib import Path

import RAG.law_data_search as law_search


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
        data_dir = root / "data_doc"
        cache_dir = root / "cache"
        law_dir = data_dir / "法律"
        law_dir.mkdir(parents=True)
        (law_dir / "中华人民共和国测试法.txt").write_text(
            "\n".join(
                [
                    "URL: https://example.test/law",
                    "中华人民共和国测试法",
                    "时效性：现行有效",
                    "公布日期：2026-01-01",
                    "施行日期：2026-01-01",
                    "第一条",
                    "本法用于测试本地法律数据库检索。",
                    "第二条",
                    "检索系统不得把 LIKE 通配符当成法律名称。",
                ]
            ),
            encoding="utf-8",
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
            source_file = data_dir / "法律" / "中华人民共和国测试法.txt"
            first = law_search.build_source_manifest()
            source_file.write_text(source_file.read_text(encoding="utf-8") + "\n第三条\n内容变更。", encoding="utf-8")
            second = law_search.build_source_manifest()

        self.assertNotEqual(first["content_sha256"], second["content_sha256"])
        self.assertNotEqual(first, second)

    def test_search_limit_is_clamped(self):
        self.assertEqual(law_search.normalize_limit(999), law_search.MAX_SEARCH_LIMIT)
        self.assertEqual(law_search.normalize_limit(-10), 1)
        self.assertEqual(law_search.normalize_limit("bad"), 5)


if __name__ == "__main__":
    unittest.main()
