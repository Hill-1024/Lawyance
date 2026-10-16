"""法律向量库 schema / fusion / 降级开关单元测试。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vector_store.config import clear_config_cache, get_legal_vector_config
from vector_store.fusion import dedupe_chunks, reciprocal_rank_fusion
from vector_store.lexical import LexicalRetriever, tokenize
from vector_store.schema import (
    LawChunk,
    make_point_id,
    map_effective_status,
    normalize_article_number,
)


class VectorStoreSchemaTests(unittest.TestCase):
    def test_normalize_article_number(self):
        self.assertEqual(normalize_article_number("第五百七十七条"), "577")
        self.assertEqual(normalize_article_number("第十七条"), "17")

    def test_map_effective_status(self):
        self.assertEqual(map_effective_status("现行有效"), "in_force")
        self.assertEqual(map_effective_status("尚未施行"), "not_yet_in_force")
        self.assertEqual(map_effective_status("废止"), "repealed")

    def test_point_id_stable(self):
        first = make_point_id(
            source_id="abc",
            article_number="第五百七十七条",
            revision_label="2020修正",
            chunk_index=0,
            content_hash_value="deadbeef",
        )
        second = make_point_id(
            source_id="abc",
            article_number="第五百七十七条",
            revision_label="2020修正",
            chunk_index=0,
            content_hash_value="deadbeef",
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 36)


class VectorStoreFusionTests(unittest.TestCase):
    def _chunk(self, source_id: str, article: str, **scores: float) -> LawChunk:
        chunk = LawChunk(
            text=f"正文{article}",
            law_name="中华人民共和国民法典",
            short_name="民法典",
            article_number=article,
            article_number_normalized=normalize_article_number(article),
            article_id="",
            source_id=source_id,
            source_file="x.json",
            content_hash="",
            law_type="法律",
            jurisdiction="CN",
            legal_system="china",
            effective_status="in_force",
        )
        chunk.ensure_ids()
        chunk.scores.update(scores)
        return chunk

    def test_dedupe_keeps_best_chunk(self):
        a = self._chunk("s1", "第五百七十七条", dense=0.2)
        b = self._chunk("s1", "第五百七十七条", dense=0.9)
        b.text = "更长的正文内容用于优先保留"
        merged = dedupe_chunks([a, b])
        self.assertEqual(len(merged), 1)
        self.assertIn("更长", merged[0].text)

    def test_rrf_prefers_exact(self):
        exact = self._chunk("s1", "第五百七十七条", exact=100.0)
        exact.routes = ["exact"]
        dense = self._chunk("s2", "第五条", dense=0.99)
        dense.routes = ["dense"]
        fused = reciprocal_rank_fusion(
            {"exact": [exact], "dense": [dense]},
            k=60,
            query_has_citation=True,
            preferred_jurisdictions={"CN"},
            preferred_systems={"china"},
            limit=5,
        )
        self.assertEqual(fused[0].article_number, "第五百七十七条")


class VectorStoreLexicalTests(unittest.TestCase):
    def test_tokenize_and_bm25_roundtrip(self):
        tokens = tokenize("迟延履行 第五百七十七条")
        self.assertTrue(tokens)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bm25.sqlite3"
            retriever = LexicalRetriever(path)
            chunk = LawChunk(
                text="当事人一方不履行合同义务或者履行合同义务不符合约定的，应当承担继续履行、采取补救措施或者赔偿损失等违约责任。",
                law_name="中华人民共和国民法典",
                short_name="民法典",
                article_number="第五百七十七条",
                article_number_normalized="577",
                article_id="",
                source_id="civilcode",
                source_file="x.json",
                content_hash="",
                law_type="法律",
                jurisdiction="CN",
                legal_system="china",
                effective_status="in_force",
            )
            chunk.ensure_ids()
            retriever.index([chunk], replace=True)
            hits = retriever.search(
                "不履行合同义务 违约责任",
                filters={"jurisdictions": ["CN"], "legal_systems": ["china"]},
                limit=5,
            )
            self.assertTrue(hits)
            self.assertEqual(hits[0].article_number, "第五百七十七条")


class VectorStoreConfigAndRouterTests(unittest.TestCase):
    def tearDown(self):
        clear_config_cache()
        for key in (
            "LAWVER_VECTOR_DB_ENABLED",
            "LAWVER_VECTOR_RETRIEVAL_ENABLED",
            "LAWVER_RERANKER_ENABLED",
        ):
            os.environ.pop(key, None)
        clear_config_cache()

    def test_hybrid_disabled_by_default(self):
        clear_config_cache()
        cfg = get_legal_vector_config()
        self.assertFalse(cfg.vector_retrieval_enabled)

    def test_search_article_falls_back_when_hybrid_disabled(self):
        from mcp.legal_search_router import search_article

        os.environ["LAWVER_VECTOR_RETRIEVAL_ENABLED"] = "0"
        clear_config_cache()
        with patch(
            "mcp.legal_search_router.china_search_article",
            return_value=json.dumps({"success": True, "result": "legacy-hit"}, ensure_ascii=False),
        ):
            payload = json.loads(search_article("违约责任", jurisdiction="中国"))
        self.assertTrue(payload.get("success"))
        self.assertIn("legacy-hit", payload.get("result", ""))

    def test_search_article_hybrid_contract_with_mocks(self):
        from mcp.legal_search_router import search_article
        from vector_store.schema import LawChunk, normalize_article_number

        os.environ["LAWVER_VECTOR_DB_ENABLED"] = "1"
        os.environ["LAWVER_VECTOR_RETRIEVAL_ENABLED"] = "1"
        clear_config_cache()
        chunk = LawChunk(
            text="应当承担违约责任。",
            law_name="中华人民共和国民法典",
            short_name="民法典",
            article_number="第五百七十七条",
            article_number_normalized=normalize_article_number("第五百七十七条"),
            article_id="",
            source_id="civilcode",
            source_file="x.json",
            content_hash="",
            law_type="法律",
            jurisdiction="CN",
            legal_system="china",
            effective_status="in_force",
        )
        chunk.ensure_ids()
        fake = {
            "success": True,
            "items": [chunk],
            "degraded": [],
            "channel_counts": {"bm25": 1},
        }
        with patch("vector_store.retrieval.hybrid_enabled", return_value=True), patch(
            "vector_store.retrieval.hybrid_search", return_value=fake
        ), patch(
            "mcp.legal_search_router.china_search_article",
            return_value=json.dumps({"success": True, "result": "should-not-use"}, ensure_ascii=False),
        ):
            payload = json.loads(search_article("违约责任", jurisdiction="中国"))
        self.assertTrue(payload.get("success"))
        self.assertIn("民法典", payload.get("result", ""))
        self.assertIn("第五百七十七条", payload.get("result", ""))
        self.assertNotIn("should-not-use", payload.get("result", ""))


class VectorStoreDenseAndRerankTests(unittest.TestCase):
    def test_dense_search_uses_query_points(self):
        from types import SimpleNamespace

        from vector_store import qdrant_client as qc

        captured = {}

        class FakeClient:
            def query_points(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    points=[
                        SimpleNamespace(
                            id="p1",
                            score=0.91,
                            payload={
                                "text": "违约责任正文",
                                "law_name": "中华人民共和国民法典",
                                "short_name": "民法典",
                                "article_number": "第五百七十七条",
                                "article_number_normalized": "577",
                                "article_id": "民法典:577",
                                "source_id": "civilcode",
                                "source_file": "x.json",
                                "content_hash": "abc",
                                "law_type": "法律",
                                "jurisdiction": "CN",
                                "legal_system": "china",
                                "effective_status": "in_force",
                            },
                        )
                    ]
                )

        with patch.object(qc, "build_client", return_value=FakeClient()), patch.object(
            qc, "get_legal_vector_config", return_value=get_legal_vector_config()
        ):
            hits = qc.dense_search([0.1, 0.2], limit=5, jurisdictions=["CN"], legal_systems=["china"])
        self.assertEqual(captured.get("query"), [0.1, 0.2])
        self.assertNotIn("query_vector", captured)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].scores.get("dense"), 0.91)
        self.assertIn("dense", hits[0].routes)

    def test_rerank_truncates_and_records_scores(self):
        from vector_store.config import LegalVectorConfig
        from vector_store.reranker import clear_reranker_failure, rerank_chunks

        clear_reranker_failure()
        chunks = []
        for index in range(5):
            chunk = LawChunk(
                text=f"正文{index}",
                law_name="中华人民共和国民法典",
                short_name="民法典",
                article_number=f"第{index + 1}条",
                article_number_normalized=str(index + 1),
                article_id="",
                source_id=f"s{index}",
                source_file="x.json",
                content_hash="",
                law_type="法律",
                jurisdiction="CN",
                legal_system="china",
                effective_status="in_force",
            )
            chunk.ensure_ids()
            chunks.append(chunk)

        cfg = LegalVectorConfig(
            vector_db_enabled=True,
            vector_retrieval_enabled=True,
            qdrant_url="http://127.0.0.1:6333",
            qdrant_api_key="",
            qdrant_collection="test",
            vector_distance="Cosine",
            vector_search_limit=50,
            vector_upsert_batch_size=64,
            embedding_base_url="http://example",
            embedding_api_key="k",
            embedding_model="m",
            embedding_version="m-v1",
            embedding_timeout=8.0,
            embedding_batch_size=32,
            embedding_max_chars=1800,
            bm25_enabled=True,
            bm25_top_k=50,
            bm25_path=Path("/tmp/bm25.sqlite3"),
            hybrid_top_k=20,
            rrf_k=60,
            final_retrieval_k=8,
            reranker_enabled=True,
            reranker_base_url="http://example",
            reranker_api_key="k",
            reranker_model="rerank-model",
            reranker_top_k=4,
            reranker_final_k=2,
            reranker_timeout=3.0,
            index_version="article-v1",
            data_version="",
            chunking_version="article-v1",
            manifest_path=Path("/tmp/manifest.json"),
            max_chunk_chars=1800,
        )
        with patch(
            "vector_store.reranker.request_rerank",
            return_value=[0.1, 0.9, 0.2, 0.3],
        ):
            ranked = rerank_chunks("违约", chunks, config=cfg)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0].article_number, "第2条")
        self.assertEqual(ranked[0].scores.get("cross_encoder_score"), 0.9)
        self.assertEqual(ranked[0].reranker_model, "rerank-model")

    def test_rerank_timeout_falls_back(self):
        from vector_store.reranker import clear_reranker_failure, mark_reranker_failure, rerank_chunks

        clear_reranker_failure()
        mark_reranker_failure(30)
        chunk = LawChunk(
            text="正文",
            law_name="中华人民共和国民法典",
            short_name="民法典",
            article_number="第五条",
            article_number_normalized="5",
            article_id="",
            source_id="s",
            source_file="x.json",
            content_hash="",
            law_type="法律",
            jurisdiction="CN",
            legal_system="china",
            effective_status="in_force",
        )
        chunk.ensure_ids()
        os.environ["LAWVER_RERANKER_ENABLED"] = "1"
        clear_config_cache()
        out = rerank_chunks("q", [chunk])
        self.assertEqual(out, [chunk])
        clear_reranker_failure()

    def test_update_index_detects_content_hash_change(self):
        from vector_store.ingest import _changed_sources_by_hash

        old = {
            "source_ids": ["s1", "s2"],
            "source_content_hashes": {"s1": ["aaa"], "s2": ["bbb"]},
        }
        c1 = LawChunk(
            text="新正文",
            law_name="法",
            short_name="",
            article_number="第一条",
            article_number_normalized="1",
            article_id="",
            source_id="s1",
            source_file="x",
            content_hash="ccc",
            law_type="法律",
            jurisdiction="CN",
            legal_system="china",
            effective_status="in_force",
        )
        c2 = LawChunk(
            text="旧",
            law_name="法",
            short_name="",
            article_number="第二条",
            article_number_normalized="2",
            article_id="",
            source_id="s2",
            source_file="x",
            content_hash="bbb",
            law_type="法律",
            jurisdiction="CN",
            legal_system="china",
            effective_status="in_force",
        )
        changed = _changed_sources_by_hash(old, [c1, c2])
        self.assertEqual(changed, {"s1"})

    def test_normalize_asean_jurisdiction(self):
        from vector_store.ingest import _normalize_jurisdiction

        self.assertEqual(_normalize_jurisdiction("indonesia"), "ID")
        self.assertEqual(_normalize_jurisdiction("TH"), "TH")
        self.assertEqual(_normalize_jurisdiction("", default="MM"), "MM")

    def test_agents_do_not_import_vector_store(self):
        """架构边界：Agent 不得直连 vector_store / qdrant。"""
        import ast
        from pathlib import Path

        agents_root = Path(__file__).resolve().parents[1] / "backend" / "agents"
        violations = []
        for path in agents_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "vector_store" or alias.name.startswith("vector_store."):
                            violations.append(str(path.relative_to(path.parents[2])))
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod == "vector_store" or mod.startswith("vector_store."):
                        violations.append(str(path.relative_to(path.parents[2])))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
