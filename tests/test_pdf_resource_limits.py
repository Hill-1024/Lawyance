"""
模块描述：PDF 文本读取的页数、文本、对象与最终输出预算回归测试。
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from mcp.PDF_processor import PDFTextExtractor, _run_pdf_isolated, pdf_commit_by_sentence, pdf_text_reader


def _slow_isolated_job(delay: float) -> str:
    time.sleep(delay)
    return "finished"


def _write_pdf(path: Path, pages: list[list[str]]) -> None:
    document = fitz.open()
    try:
        for lines in pages:
            page = document.new_page()
            for index, line in enumerate(lines):
                page.insert_text((50, 50 + index * 14), line, fontsize=10)
        document.save(path)
    finally:
        document.close()


class PDFResourceLimitTests(unittest.TestCase):
    def test_isolated_worker_is_terminated_at_hard_deadline(self):
        started_at = time.monotonic()

        status, payload = _run_pdf_isolated(_slow_isolated_job, (1.0,), {}, 0.05)

        self.assertEqual(status, "timeout")
        self.assertIsNone(payload)
        self.assertLess(time.monotonic() - started_at, 1.0)

    def test_input_file_size_is_checked_before_native_parser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "oversized.pdf"
            path.write_bytes(b"%PDF" + (b"x" * 64))
            with patch("mcp.PDF_processor.MAX_PDF_INPUT_BYTES", 16):
                payload = json.loads(pdf_text_reader(path))

        self.assertIn("超过大小限制", payload["error"])

    def test_wall_clock_budget_stops_after_an_expensive_page(self):
        class SlowPage:
            def get_text(self, _mode):
                time.sleep(0.03)
                return [(0, 0, 1, 1, "late", 0, 0, 0)]

        class FakeDocument:
            def __len__(self):
                return 1

            def __getitem__(self, _index):
                return SlowPage()

            def xref_length(self):
                return 0

        extractor = PDFTextExtractor(max_wall_seconds=0.01)
        extractor.doc = FakeDocument()

        pages = extractor.extract_sentences_with_coords()

        self.assertEqual(pages, [])
        self.assertIn("max_wall_seconds", extractor.truncated_reasons)

    def test_small_pdf_keeps_all_content_and_reports_not_truncated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "small.pdf"
            _write_pdf(path, [["First sentence. Second sentence!"], ["Third sentence?"]])

            raw = pdf_text_reader(path, max_output_bytes=20_000)
            payload = json.loads(raw)

        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["truncated_reasons"], [])
        self.assertEqual(len(payload["pages"]), 2)
        extracted = " ".join(
            sentence["text"]
            for page in payload["pages"]
            for sentence in page["sentences"]
        )
        self.assertIn("First sentence.", extracted)
        self.assertIn("Second sentence!", extracted)
        self.assertIn("Third sentence?", extracted)
        self.assertLessEqual(len(raw.encode("utf-8")), 20_000)

    def test_annotation_worker_publishes_output_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.pdf"
            output_path = Path(temp_dir) / "annotated.pdf"
            _write_pdf(input_path, [["Review this sentence."]])

            success, published_path = pdf_commit_by_sentence(
                input_path,
                "Checked",
                page_index=0,
                sentence_index=0,
                output_path=output_path,
            )

            self.assertTrue(success)
            self.assertEqual(Path(published_path), output_path)
            self.assertTrue(output_path.is_file())
            self.assertEqual(list(Path(temp_dir).glob(".lawver-pdf-*")), [])
            document = fitz.open(output_path)
            try:
                self.assertIsNotNone(document[0].first_annot)
            finally:
                document.close()

    def test_page_limit_stops_before_extra_pages_with_explicit_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "pages.pdf"
            _write_pdf(path, [["Page one."], ["Page two."], ["Page three."]])
            payload = json.loads(pdf_text_reader(path, max_pages=2))

        self.assertTrue(payload["truncated"])
        self.assertIn("max_pages", payload["truncated_reasons"])
        self.assertEqual([page["page"] for page in payload["pages"]], [1, 2])

    def test_extracted_character_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "characters.pdf"
            lines = [f"Line {index}: " + ("x" * 48) + "." for index in range(20)]
            _write_pdf(path, [lines])
            payload = json.loads(pdf_text_reader(path, max_extracted_chars=120))

        self.assertTrue(payload["truncated"])
        self.assertIn("max_extracted_chars", payload["truncated_reasons"])
        self.assertLessEqual(payload["stats"]["extracted_chars"], 120)

    def test_pdf_object_limit_fails_closed_before_page_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "objects.pdf"
            _write_pdf(path, [["Object constrained PDF."]])
            payload = json.loads(pdf_text_reader(path, max_objects=1))

        self.assertTrue(payload["truncated"])
        self.assertIn("max_objects", payload["truncated_reasons"])
        self.assertEqual(payload["pages"], [])

    def test_final_utf8_output_limit_returns_valid_json_with_reason(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "output.pdf"
            pages = [
                [f"Page {page} line {line}: " + ("payload " * 10) + "." for line in range(20)]
                for page in range(4)
            ]
            _write_pdf(path, pages)
            raw = pdf_text_reader(path, max_output_bytes=700)
            payload = json.loads(raw)

        self.assertLessEqual(len(raw.encode("utf-8")), 700)
        self.assertTrue(payload["truncated"])
        self.assertIn("max_output_bytes", payload["truncated_reasons"])


if __name__ == "__main__":
    unittest.main()
