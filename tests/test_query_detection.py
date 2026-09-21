"""Language and jurisdiction hints must preserve cross-border distinctions."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.query_detection import (
    JURISDICTION_ALIGNMENT_LANGUAGES,
    _call_polylm,
    align_query_with_polylm,
    detect_query,
    detect_query_with_polylm,
)


class QueryDetectionTests(unittest.TestCase):
    def test_alignment_languages_follow_database_corpus_convention(self):
        self.assertEqual(JURISDICTION_ALIGNMENT_LANGUAGES["TH"], "th")
        self.assertEqual(JURISDICTION_ALIGNMENT_LANGUAGES["VN"], "vi")
        self.assertEqual(JURISDICTION_ALIGNMENT_LANGUAGES["ID"], "id")
        for code in ("MY", "SG", "MM", "PH", "BN"):
            with self.subTest(code=code):
                self.assertEqual(JURISDICTION_ALIGNMENT_LANGUAGES[code], "en")

    def test_same_thai_target_across_input_languages(self):
        samples = {
            "th": "บริษัทจีนสามารถถือหุ้น 100% ในบริษัทไทยได้หรือไม่?",
            "en": "Can a Chinese company wholly own a Thai company?",
            "zh": "中国企业能否100%持有泰国公司的股权？",
            "vi": "Công ty Trung Quốc có thể sở hữu 100% công ty Thái Lan không?",
            "id": "Apakah perusahaan Tiongkok dapat memiliki 100% saham perusahaan Thailand?",
            "ms": "Bolehkah syarikat China memiliki 100% saham syarikat Thailand?",
        }
        for language, query in samples.items():
            with self.subTest(language=language):
                result = detect_query(query)
                self.assertEqual(result.language, language)
                self.assertEqual(result.jurisdiction, "TH")
                self.assertEqual(result.mentioned_jurisdictions, ("CN", "TH"))

    def test_language_does_not_choose_jurisdiction(self):
        result = detect_query("กฎหมายจีนใช้กับสัญญานี้หรือไม่?")
        self.assertEqual(result.language, "th")
        self.assertEqual(result.jurisdiction, "CN")

    def test_multiple_legal_systems_remain_ambiguous(self):
        for query in ("比较中国法律与泰国法律", "Compare Chinese and Thai law"):
            with self.subTest(query=query):
                result = detect_query(query)
                self.assertIsNone(result.jurisdiction)
                self.assertEqual(result.mentioned_jurisdictions, ("CN", "TH"))

    def test_no_country_is_not_assumed_from_language(self):
        result = detect_query("需要法律咨询")
        self.assertEqual(result.language, "zh")
        self.assertIsNone(result.jurisdiction)
        self.assertEqual(result.mentioned_jurisdictions, ())

    def test_short_or_substring_input_is_unknown(self):
        self.assertEqual(detect_query("ok").language, "und")
        self.assertIsNone(detect_query("Thailandia").jurisdiction)


class PolyLMDetectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_result_is_used_when_configured(self):
        query = "Can a Chinese company wholly own a Thai company?"
        response = '{"language":"en","jurisdiction":"TH","mentioned_jurisdictions":["CN","TH"]}'
        with patch.dict(os.environ, {"POLYLM_BASE_URL": "http://127.0.0.1:8001/v1", "POLYLM_MODEL": "polylm", "POLYLM_API_KEY": "sample-key"}), \
             patch("services.query_detection._call_polylm", new_callable=AsyncMock) as call:
            call.return_value = response
            result = await detect_query_with_polylm(query)

        call.assert_awaited_once_with(query, "http://127.0.0.1:8001/v1", "polylm", "sample-key")
        self.assertEqual(result.as_payload(), {
            "language": "en", "jurisdiction": "TH",
            "mentioned_jurisdictions": ["CN", "TH"], "source": "polylm",
        })

    async def test_bad_model_response_falls_back_to_rules(self):
        with patch.dict(os.environ, {"POLYLM_BASE_URL": "http://127.0.0.1:8001/v1", "POLYLM_MODEL": "polylm"}), \
             patch("services.query_detection._call_polylm", new_callable=AsyncMock) as call:
            call.return_value = '{"language":"en","jurisdiction":"XX","mentioned_jurisdictions":[]}'
            result = await detect_query_with_polylm("Can a Chinese company own a Thai company?")

        self.assertEqual(result.jurisdiction, "TH")
        self.assertEqual(result.source, "rules_fallback")

    async def test_no_model_config_uses_rules_without_call(self):
        with patch.dict(os.environ, {"POLYLM_BASE_URL": "", "POLYLM_MODEL": ""}), \
             patch("services.query_detection._call_polylm", new_callable=AsyncMock) as call:
            result = await detect_query_with_polylm("泰国公司的法律问题")

        call.assert_not_awaited()
        self.assertEqual(result.source, "rules")
        self.assertEqual(result.jurisdiction, "TH")

    async def test_request_uses_independent_openai_compatible_endpoint(self):
        captured = {}

        class FakeClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"language":"th","jurisdiction":"TH","mentioned_jurisdictions":["TH"]}'))])

        with patch.dict(os.environ, {"POLYLM_API_MODE": "chat"}), \
             patch("llm.client.build_client", return_value=FakeClient()) as factory:
            content = await _call_polylm("ข้อความทดสอบ", "http://127.0.0.1:8001/v1", "polylm", "key")

        factory.assert_called_once_with("key", "http://127.0.0.1:8001/v1")
        self.assertEqual(captured["model"], "polylm")
        self.assertEqual(captured["temperature"], 0)
        self.assertIn("aligned_query", captured["messages"][0]["content"])
        self.assertIn("english_pivot", captured["messages"][0]["content"])
        self.assertIn("legal_concepts", captured["messages"][0]["content"])
        self.assertIn("never multiple views", captured["messages"][0]["content"])
        self.assertIn("ข้อความทดสอบ", captured["messages"][1]["content"])
        schema = captured["response_format"]["json_schema"]["schema"]
        self.assertIn("english_pivot", schema["required"])
        self.assertIn("legal_concepts", schema["required"])
        self.assertIn('"jurisdiction":"TH"', content)

    async def test_base_model_can_use_completions_endpoint(self):
        captured = {}

        class FakeClient:
            def __init__(self):
                self.completions = self

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(choices=[SimpleNamespace(text=(
                    '{"language":"zh","jurisdiction":"TH",'
                    '"mentioned_jurisdictions":["CN","TH"],'
                    '"aligned_query":"การถือหุ้นของบริษัทต่างชาติ"}'
                ))])

        with patch.dict(os.environ, {"POLYLM_API_MODE": "completion"}), \
             patch("llm.client.build_client", return_value=FakeClient()) as factory:
            content = await _call_polylm("中国企业投资泰国", "http://127.0.0.1:8001/v1", "polylm", "key")

        factory.assert_called_once_with("key", "http://127.0.0.1:8001/v1")
        self.assertEqual(captured["model"], "polylm")
        self.assertIn("Input JSON", captured["prompt"])
        self.assertIn("中国企业投资泰国", captured["prompt"])
        self.assertNotIn("messages", captured)
        self.assertIn("json", captured["extra_body"]["structured_outputs"])
        self.assertIn('"aligned_query"', content)


class SemanticGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_aligns_to_target_jurisdiction_corpus_language(self):
        query = "中国企业能否100%持有泰国公司的股权？"
        response = (
            '{"language":"zh","jurisdiction":"TH",'
            '"mentioned_jurisdictions":["CN","TH"],'
            '"aligned_query":"บริษัทจีนถือหุ้น 100% ในบริษัทไทย",'
            '"english_pivot":"Whether a Chinese company may own 100% of a Thai company",'
            '"legal_concepts":["foreign ownership","foreign ownership",'
            '"foreign investment restriction"]}'
        )
        with patch.dict(os.environ, {
            "POLYLM_BASE_URL": "http://127.0.0.1:8001/v1",
            "POLYLM_MODEL": "PolyLM-Qwen-7B",
            "POLYLM_API_KEY": "sample-key",
        }), patch("services.query_detection._call_polylm", new_callable=AsyncMock) as call:
            call.return_value = response
            result = await align_query_with_polylm(query)

        call.assert_awaited_once_with(
            query,
            "http://127.0.0.1:8001/v1",
            "PolyLM-Qwen-7B",
            "sample-key",
        )
        self.assertEqual(result.as_payload(), {
            "language": "zh",
            "jurisdiction": "TH",
            "mentioned_jurisdictions": ["CN", "TH"],
            "source": "polylm",
            "jurisdiction_label": "泰国",
            "original_query": query,
            "aligned_query": "บริษัทจีนถือหุ้น 100% ในบริษัทไทย",
            "alignment_language": "th",
            "aligned": True,
            "english_pivot": "Whether a Chinese company may own 100% of a Thai company",
            "legal_concepts": ["foreign ownership", "foreign investment restriction"],
        })

    async def test_wrong_language_is_repaired_once(self):
        query = "中国企业能否100%持有泰国公司的股权？"
        response = (
            '{"language":"zh","jurisdiction":"TH",'
            '"mentioned_jurisdictions":["CN","TH"],'
            '"aligned_query":"中国企业能否100%持有泰国公司的股权？",'
            '"english_pivot":"Whether a Chinese company may own 100% of a Thai company",'
            '"legal_concepts":["foreign ownership"]}'
        )
        with patch.dict(os.environ, {
            "POLYLM_BASE_URL": "http://127.0.0.1:8001/v1",
            "POLYLM_MODEL": "semantic-model",
            "POLYLM_API_KEY": "sample-key",
        }), patch(
            "services.query_detection._call_polylm",
            new_callable=AsyncMock,
        ) as call, patch(
            "services.query_detection._repair_aligned_query",
            new_callable=AsyncMock,
        ) as repair:
            call.return_value = response
            repair.return_value = "บริษัทจีนสามารถถือหุ้นในบริษัทไทยได้ 100% หรือไม่?"
            result = await align_query_with_polylm(query)

        repair.assert_awaited_once_with(
            query,
            "th",
            "http://127.0.0.1:8001/v1",
            "semantic-model",
            "sample-key",
        )
        self.assertTrue(result.aligned)
        self.assertEqual(result.alignment_language, "th")
        self.assertIn("บริษัท", result.aligned_query)
        self.assertEqual(
            result.english_pivot,
            "Whether a Chinese company may own 100% of a Thai company",
        )
        self.assertEqual(result.legal_concepts, ("foreign ownership",))

    async def test_wrong_language_after_repair_falls_back(self):
        query = "中国企业能否100%持有泰国公司的股权？"
        response = (
            '{"language":"zh","jurisdiction":"TH",'
            '"mentioned_jurisdictions":["CN","TH"],'
            '"aligned_query":"中国企业能否100%持有泰国公司的股权？",'
            '"english_pivot":"Whether a Chinese company may own 100% of a Thai company",'
            '"legal_concepts":["foreign ownership"]}'
        )
        with patch.dict(os.environ, {
            "POLYLM_BASE_URL": "http://127.0.0.1:8001/v1",
            "POLYLM_MODEL": "semantic-model",
        }), patch(
            "services.query_detection._call_polylm",
            new_callable=AsyncMock,
        ) as call, patch(
            "services.query_detection._repair_aligned_query",
            new_callable=AsyncMock,
        ) as repair:
            call.return_value = response
            repair.return_value = query
            result = await align_query_with_polylm(query)

        self.assertFalse(result.aligned)
        self.assertEqual(result.aligned_query, query)
        self.assertEqual(result.detection.source, "rules_fallback")

    async def test_ambiguous_comparison_stays_single_source_language_query(self):
        query = "Compare Chinese and Thai law on foreign ownership"
        response = (
            '{"language":"en","jurisdiction":null,'
            '"mentioned_jurisdictions":["CN","TH"],'
            '"aligned_query":"compare foreign ownership restrictions under Chinese and Thai law",'
            '"english_pivot":"A paraphrase that must not replace the English input",'
            '"legal_concepts":["foreign ownership","comparative law"]}'
        )
        with patch.dict(os.environ, {
            "POLYLM_BASE_URL": "http://127.0.0.1:8001/v1",
            "POLYLM_MODEL": "PolyLM-Qwen-7B",
        }), patch("services.query_detection._call_polylm", new_callable=AsyncMock) as call:
            call.return_value = response
            result = await align_query_with_polylm(query)

        self.assertIsNone(result.detection.jurisdiction)
        self.assertEqual(result.alignment_language, "en")
        self.assertIsInstance(result.aligned_query, str)
        self.assertTrue(result.aligned)
        self.assertEqual(result.english_pivot, query)
        self.assertEqual(result.legal_concepts, ("foreign ownership", "comparative law"))

    async def test_invalid_alignment_falls_back_without_guessing_translation(self):
        query = "中国企业能否持有泰国公司的股权？"
        with patch.dict(os.environ, {
            "POLYLM_BASE_URL": "http://127.0.0.1:8001/v1",
            "POLYLM_MODEL": "PolyLM-Qwen-7B",
        }), patch("services.query_detection._call_polylm", new_callable=AsyncMock) as call:
            call.return_value = (
                '{"language":"zh","jurisdiction":"TH",'
                '"mentioned_jurisdictions":["CN","TH"],"aligned_query":"",'
                '"english_pivot":"Whether a Chinese company may own a Thai company",'
                '"legal_concepts":["foreign ownership"]}'
            )
            result = await align_query_with_polylm(query)

        self.assertFalse(result.aligned)
        self.assertEqual(result.aligned_query, query)
        self.assertEqual(result.alignment_language, "zh")
        self.assertEqual(result.detection.source, "rules_fallback")

    async def test_unconfigured_english_query_reuses_original_as_pivot(self):
        query = "Can a Chinese company wholly own a Thai company?"
        with patch.dict(os.environ, {"POLYLM_BASE_URL": "", "POLYLM_MODEL": ""}):
            result = await align_query_with_polylm(query)

        self.assertFalse(result.aligned)
        self.assertEqual(result.english_pivot, query)
        self.assertEqual(result.legal_concepts, ())


if __name__ == "__main__":
    unittest.main()
