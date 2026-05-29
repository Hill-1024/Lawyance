"""
模块描述：法律文书 block text 清洗器与元评论 soft warning 测试。
覆盖 HTML 角标转换、包装标签剥离、HTML 实体解码、元评论检测等场景。
"""

from __future__ import annotations

import unittest

from mcp.legal_document.text_cleaner import clean_block_text, merge_refs
from mcp.legal_document.validator import evaluate_soft_constraints


class CleanBlockTextTests(unittest.TestCase):
    def test_sup_link_converted_and_ref_collected(self):
        text = '根据《民法典》第六百七十五条<sup><a href="https://x.com/law/675">1</a></sup>之规定...'
        cleaned, refs = clean_block_text(text)
        self.assertEqual(cleaned, "根据《民法典》第六百七十五条[1]之规定...")
        self.assertEqual(refs, [{"label": "1", "url": "https://x.com/law/675"}])

    def test_web_search_sup_label_preserved(self):
        text = '据报道<sup><a href="https://news.example.com/a">网1</a></sup>...'
        cleaned, refs = clean_block_text(text)
        self.assertIn("[网1]", cleaned)
        self.assertEqual(refs[0]["label"], "网1")
        self.assertEqual(refs[0]["url"], "https://news.example.com/a")

    def test_multiple_sup_links(self):
        text = (
            '《民法典》第一条<sup><a href="https://u1">1</a></sup>'
            '与《民法典》第二条<sup><a href="https://u2">2</a></sup>'
        )
        cleaned, refs = clean_block_text(text)
        self.assertIn("[1]", cleaned)
        self.assertIn("[2]", cleaned)
        self.assertEqual(len(refs), 2)
        self.assertEqual({r["url"] for r in refs}, {"https://u1", "https://u2"})

    def test_plain_sup_without_anchor(self):
        cleaned, refs = clean_block_text("脚注<sup>1</sup>说明")
        self.assertEqual(cleaned, "脚注[1]说明")
        self.assertEqual(refs, [])

    def test_final_answer_wrapper_stripped(self):
        cleaned, _ = clean_block_text("<final_answer>请求判令被告偿还借款本金</final_answer>")
        self.assertEqual(cleaned, "请求判令被告偿还借款本金")
        self.assertNotIn("<", cleaned)
        self.assertNotIn(">", cleaned)

    def test_think_wrapper_stripped(self):
        cleaned, _ = clean_block_text("<think>思考</think>正文内容")
        self.assertEqual(cleaned, "正文内容")

    def test_think_refs_not_collected(self):
        text = '<think>内部<sup><a href="https://hidden.test">1</a></sup></think>正文'
        cleaned, refs = clean_block_text(text)
        self.assertEqual(cleaned, "正文")
        self.assertEqual(refs, [])

    def test_generic_html_tags_stripped(self):
        cleaned, _ = clean_block_text("<b>重点</b>请求<i>事项</i><span>说明</span>")
        self.assertEqual(cleaned, "重点请求事项说明")

    def test_html_entities_decoded(self):
        cleaned, _ = clean_block_text("金额 &lt; 200,000 元 &amp; 利息 &gt; 0")
        self.assertEqual(cleaned, "金额 < 200,000 元 & 利息 > 0")

    def test_escaped_html_tags_cleaned(self):
        cleaned, refs = clean_block_text(
            '根据条文&lt;sup&gt;&lt;a href="https://x.test/law?a=1&amp;b=2"&gt;1&lt;/a&gt;&lt;/sup&gt;'
        )
        self.assertEqual(cleaned, "根据条文[1]")
        self.assertEqual(refs, [{"label": "1", "url": "https://x.test/law?a=1&b=2"}])
        cleaned, _ = clean_block_text("&lt;final_answer&gt;请求返还本金&lt;/final_answer&gt;")
        self.assertEqual(cleaned, "请求返还本金")

    def test_composite_pollution(self):
        text = (
            '<final_answer>根据《民法典》第六百七十五条<sup><a href="https://u">1</a></sup>,'
            '请求判令被告偿还本金。我这样写是因为体现了请求的具体性。</final_answer>'
        )
        cleaned, refs = clean_block_text(text)
        self.assertNotIn("<final_answer>", cleaned)
        self.assertIn("[1]", cleaned)
        # 元评论保留 — 由 prompt + soft warning 处理,不在 cleaner 范围
        self.assertIn("我这样写是因为", cleaned)
        self.assertEqual(refs[0]["url"], "https://u")

    def test_empty_and_none_inputs(self):
        self.assertEqual(clean_block_text(""), ("", []))
        self.assertEqual(clean_block_text(None), ("", []))
        self.assertEqual(clean_block_text("   \n  \n  "), ("", []))

    def test_pure_text_unchanged(self):
        cleaned, refs = clean_block_text("纯文本无标签")
        self.assertEqual(cleaned, "纯文本无标签")
        self.assertEqual(refs, [])

    def test_inline_newlines_preserved(self):
        cleaned, _ = clean_block_text("第一行\n第二行\n第三行")
        self.assertEqual(cleaned, "第一行\n第二行\n第三行")

    def test_whitespace_collapse(self):
        cleaned, _ = clean_block_text("多      个     空格")
        self.assertEqual(cleaned, "多 个 空格")
        cleaned, _ = clean_block_text("行末空格   \n下一行")
        self.assertEqual(cleaned, "行末空格\n下一行")

    def test_case_and_whitespace_tolerant(self):
        cleaned, refs = clean_block_text('<SUP><A HREF="https://x">1</A></SUP>')
        self.assertEqual(cleaned, "[1]")
        self.assertEqual(refs, [{"label": "1", "url": "https://x"}])
        cleaned, refs = clean_block_text('< sup >< a href = "https://x" > 1 </ a >< / sup >')
        self.assertEqual(cleaned, "[1]")
        self.assertEqual(refs[0]["url"], "https://x")

    def test_empty_sup_uses_placeholder(self):
        cleaned, _ = clean_block_text("<sup></sup>")
        self.assertEqual(cleaned, "[?]")

    def test_non_string_input_coerced(self):
        cleaned, _ = clean_block_text(123)
        self.assertEqual(cleaned, "123")


class MergeRefsTests(unittest.TestCase):
    def test_dedup_by_url_preserves_first_label(self):
        merged = merge_refs(
            [{"label": "1", "url": "https://a"}],
            [{"label": "2", "url": "https://a"}, {"label": "3", "url": "https://b"}],
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["label"], "1")
        self.assertEqual(merged[1]["url"], "https://b")

    def test_empty_inputs(self):
        self.assertEqual(merge_refs([], []), [])
        self.assertEqual(merge_refs([{"label": "1", "url": "https://a"}], []),
                         [{"label": "1", "url": "https://a"}])


class MetaCommentSoftWarningTests(unittest.TestCase):
    """元评论检测:不修改正文,但触发软警告。"""

    GUIDE = {
        "required_sections": [],
        "soft_warnings": [],
    }

    def _eval(self, blocks: list[dict]) -> list[str]:
        return evaluate_soft_constraints(blocks, self.GUIDE)

    def test_meta_comment_i_wrote_this_because(self):
        blocks = [
            {"type": "title", "text": "民事起诉状"},
            {"type": "paragraph", "text": "原告认为被告应当偿还借款。我这样写是因为体现请求具体性。"},
            {"type": "signature_block", "signer": "张三", "date": "2026年5月28日"},
        ]
        warnings = self._eval(blocks)
        self.assertTrue(any("元评论" in w for w in warnings), warnings)

    def test_meta_comment_following_is_revised(self):
        blocks = [
            {"type": "title", "text": "民事起诉状"},
            {"type": "paragraph", "text": "以下是修改后的诉讼请求:被告偿还本金。"},
            {"type": "signature_block", "signer": "张三", "date": "2026年5月28日"},
        ]
        warnings = self._eval(blocks)
        self.assertTrue(any("元评论" in w for w in warnings), warnings)

    def test_meta_comment_above_is_draft(self):
        blocks = [
            {"type": "paragraph", "text": "以上为草拟稿,仅供参考。"},
        ]
        warnings = self._eval(blocks)
        self.assertTrue(any("元评论" in w for w in warnings), warnings)

    def test_meta_comment_consult_lawyer(self):
        blocks = [
            {"type": "paragraph", "text": "如有疑问请咨询执业律师。"},
        ]
        warnings = self._eval(blocks)
        self.assertTrue(any("元评论" in w for w in warnings), warnings)

    def test_meta_comment_author_note(self):
        blocks = [
            {"type": "paragraph", "text": "原告主张本金返还(此处补充:具体金额待定)。"},
        ]
        warnings = self._eval(blocks)
        self.assertTrue(any("元评论" in w for w in warnings), warnings)

    def test_meta_comment_author_note_fullwidth_colon(self):
        blocks = [
            {"type": "paragraph", "text": "原告主张本金返还(此处补充：具体金额待定)。"},
        ]
        warnings = self._eval(blocks)
        self.assertTrue(any("元评论" in w for w in warnings), warnings)

    def test_clean_document_no_meta_warning(self):
        blocks = [
            {"type": "title", "text": "民事起诉状"},
            {"type": "paragraph", "text": "原告与被告于 2023 年 6 月 1 日签订借款合同,约定借款本金人民币 20 万元。"},
            {"type": "heading", "level": 2, "text": "诉讼请求"},
            {"type": "ordered_list", "items": ["请求判令被告偿还借款本金 20 万元。"]},
            {"type": "signature_block", "signer": "张三", "date": "2026年5月28日"},
        ]
        warnings = self._eval(blocks)
        self.assertFalse(any("元评论" in w for w in warnings), warnings)

    def test_meta_comment_scans_list_items(self):
        blocks = [
            {"type": "title", "text": "民事起诉状"},
            {"type": "ordered_list", "items": [
                "请求判令被告偿还借款本金。",
                "(此处补充:被告应支付迟延履行违约金。)",
            ]},
        ]
        warnings = self._eval(blocks)
        self.assertTrue(any("元评论" in w for w in warnings), warnings)

    def test_meta_comment_scans_table_cells(self):
        blocks = [
            {"type": "title", "text": "证据清单"},
            {"type": "table", "header": ["序号", "证据名称", "证明事项"], "rows": [
                ["1", "借条", "借贷关系成立(此处补充:原件由原告持有)"],
            ]},
        ]
        warnings = self._eval(blocks)
        self.assertTrue(any("元评论" in w for w in warnings), warnings)


if __name__ == "__main__":
    unittest.main()
