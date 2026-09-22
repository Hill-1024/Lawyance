"""从已采集的官方 PDF 按条拆出伊斯兰库支撑条文。

只使用 sources/ 里已有的 PDF，不编造条文。拆出的记录是 record_grade=support：
机器切分、未逐条人工核验，不替代 16 条 formal 结论。

用法（仓库根目录）：
  .venv/bin/python -m RAG.islamic_law.scripts.extract_statute_articles
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

BASE = Path(__file__).resolve().parents[1]
SOURCES = BASE / "sources"
MAX_CONTENT = 12000

PASAL_RE = re.compile(r"(?m)^Pasal\s+(\d+[A-Za-z]*)\s*$")
PENJELASAN_RE = re.compile(r"(?m)^PENJELASAN\s*$")
MY_SECTION_RE = re.compile(r"(?m)^(\d+[A-Z]?)\.\s+")
HEADER_RE = re.compile(
    r"^(?:"
    r"Laws of Malaysia|LAWS OF MALAYSIA|ACT \d+|Act \d+|"
    r"SALINAN|PRESIDEN REPUBLIK INDONESIA,?|"
    r"- ?\d+ ?-|\d+"
    r")$"
)

INSTRUMENTS = [
    {
        "pdf": "ID/halal_bpjph/UU_33_2014_Jaminan_Produk_Halal.pdf",
        "country": "ID",
        "language": "id",
        "code": "UU33-2014",
        "law_name": "Undang-Undang Nomor 33 Tahun 2014 tentang Jaminan Produk Halal",
        "url": "https://cmsbl.halal.go.id/",
        "effective_date": "2014-10-17",
        "kind": "pasal",
    },
    {
        "pdf": "ID/halal_bpjph/PP_42_2024_Penyelenggaraan_JPH.pdf",
        "country": "ID",
        "language": "id",
        "code": "PP42-2024",
        "law_name": "Peraturan Pemerintah Nomor 42 Tahun 2024 tentang Penyelenggaraan Bidang Jaminan Produk Halal",
        "url": "https://cmsbl.halal.go.id/",
        "effective_date": "2024-10-17",
        "kind": "pasal",
    },
    {
        "pdf": "ID/islamic_finance/UU_21_2008_Perbankan_Syariah.pdf",
        "country": "ID",
        "language": "id",
        "code": "UU21-2008",
        "law_name": "Undang-Undang Republik Indonesia Nomor 21 Tahun 2008 tentang Perbankan Syariah",
        "url": "https://ojk.go.id/id/kanal/syariah/regulasi/undang-undang/Pages/Undang-Undang-Nomor-21-Tahun-2008-Tentang-Perbankan-Syariah.aspx",
        "effective_date": "2008-07-16",
        "kind": "pasal",
    },
    {
        "pdf": "ID/islamic_finance/POJK_16_2022_Bank_Umum_Syariah.pdf",
        "country": "ID",
        "language": "id",
        "code": "POJK16-2022",
        "law_name": "Peraturan Otoritas Jasa Keuangan Nomor 16/POJK.03/2022 tentang Bank Umum Syariah",
        "url": "https://www.ojk.go.id/",
        "effective_date": "2022-08-29",
        "kind": "pasal",
    },
    {
        "pdf": "ID/islamic_finance/POJK_18_2015_Sukuk.pdf",
        "country": "ID",
        "language": "id",
        "code": "POJK18-2015",
        "law_name": "Peraturan Otoritas Jasa Keuangan Nomor 18/POJK.04/2015 tentang Penerbitan dan Persyaratan Sukuk",
        "url": "https://www.ojk.go.id/",
        "effective_date": "2015-11-03",
        "kind": "pasal",
    },
    {
        "pdf": "MY/ifsa2013/IFSA2013_Act759_AGC_revised2021.pdf",
        "country": "MY",
        "language": "en",
        "code": "IFSA-2013",
        "law_name": "Islamic Financial Services Act 2013",
        "url": "https://lom.agc.gov.my/",
        "effective_date": "2013-03-22",
        "kind": "section",
    },
    {
        "pdf": "MY/cba2009/CBA2009_Act701_AGC.pdf",
        "country": "MY",
        "language": "en",
        "code": "CBA-2009",
        "law_name": "Central Bank of Malaysia Act 2009",
        "url": "https://lom.agc.gov.my/",
        "effective_date": "2009-09-03",
        "kind": "section",
    },
]


def read_pdf(path: Path) -> str:
    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text("text") for page in doc)
    finally:
        doc.close()


def clean_body(text: str) -> str:
    kept: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line or HEADER_RE.match(line):
            continue
        if line.endswith("-") and kept:
            kept[-1] = kept[-1] + line[:-1]
            continue
        if kept and kept[-1][-1] not in ".:;!?。":
            kept[-1] = f"{kept[-1]} {line}"
        else:
            kept.append(line)
    body = re.sub(r"\s+", " ", " ".join(kept)).strip()
    if len(body) > MAX_CONTENT:
        body = body[: MAX_CONTENT - 1].rstrip() + "…"
    return body


def _prefer_first(chunks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    for number, body in chunks:
        if number in seen:
            continue
        seen.add(number)
        rows.append((number, body))
    return rows


def _section_key(number: str) -> tuple[int, str]:
    match = re.match(r"(\d+)([A-Z]?)", number)
    if match is None:
        return (0, "")
    return (int(match.group(1)), match.group(2))


def _sequential(matches: list[re.Match[str]]) -> list[re.Match[str]]:
    """只接受递增条号，避免正文里的列表编号被当成新条文。"""
    accepted: list[re.Match[str]] = []
    last = (0, "")
    for match in matches:
        key = _section_key(match.group(1))
        if key <= last:
            continue
        if last[0] and key[0] > last[0] + 2:
            continue
        accepted.append(match)
        last = key
    return accepted


def split_pasal(text: str) -> list[tuple[str, str, str]]:
    pen = PENJELASAN_RE.search(text)
    pen_at = pen.start() if pen else len(text) + 1
    matches = list(PASAL_RE.finditer(text))
    operative: list[tuple[str, str]] = []
    penjelasan: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = clean_body(text[match.end() : end])
        if len(body) < 80:
            continue
        bucket = penjelasan if match.start() >= pen_at else operative
        bucket.append((match.group(1), body))
    rows: list[tuple[str, str, str]] = []
    for number, body in _prefer_first(operative):
        rows.append((number, f"Pasal {number}", body))
    for number, body in _prefer_first(penjelasan):
        folded = body.casefold()
        if folded in {"cukup jelas.", "cukup jelas"} or folded.startswith("cukup jelas."):
            continue
        rows.append((number, f"Penjelasan Pasal {number}", body))
    return rows


def split_sections(text: str) -> list[tuple[str, str, str]]:
    start = text.find("ENACTED by the Parliament")
    body_text = text[start:] if start >= 0 else text
    matches = _sequential(list(MY_SECTION_RE.finditer(body_text)))
    rows: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body_text)
        body = clean_body(body_text[match.end() : end])
        if len(body) < 40:
            continue
        rows.append((match.group(1), f"Section {match.group(1)}", body))
    return rows


def article_key(country: str, code: str, number: str, penjelasan: bool) -> str:
    token = re.sub(r"[^0-9A-Za-z]", "", number).upper()
    prefix = "PENJ" if penjelasan else "ART"
    return f"{country}-{code}-{prefix}-{token}"


def rule_id(country: str, code: str, number: str, penjelasan: bool) -> str:
    token = re.sub(r"[^0-9A-Za-z]", "", number).upper()
    kind = "PENJ" if penjelasan else "P"
    return f"{country}-{code}-{kind}{token}"


def build_record(spec: dict, number: str, article_number: str, content: str) -> dict:
    penjelasan = article_number.startswith("Penjelasan")
    label = "Indonesia" if spec["country"] == "ID" else "Malaysia"
    return {
        "rule_id": rule_id(spec["country"], spec["code"], number, penjelasan),
        "article_key": article_key(spec["country"], spec["code"], number, penjelasan),
        "source_id": f"pdf:{spec['pdf']}#{article_number}",
        "law_name": spec["law_name"],
        "article_number": article_number,
        "content": content,
        "url": spec["url"],
        "status": "unknown",
        "effective_date": spec["effective_date"],
        "language": spec["language"],
        "country": spec["country"],
        "country_label": label,
        "rule_subject": article_number,
        "sharia_source_type": "Statute",
        "legal_effect": "binding",
        "applicability_territory": "印度尼西亚全境" if spec["country"] == "ID" else "马来西亚",
        "output_annotation": (
            "record_grade=support；由本地官方 PDF 机器切条，未逐条人工核验；"
            "不得替代 formal 合规结论；效力状态未单独核验，故 status=unknown。"
            f" 来源文件 {spec['pdf']}。"
        ),
        "national_transformation": "成文法原文层，供检索；合规结论仍以 formal 条目为准。",
    }


def extract() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {"ID": [], "MY": []}
    seen: set[str] = set()
    for spec in INSTRUMENTS:
        text = read_pdf(SOURCES / spec["pdf"])
        pieces = split_pasal(text) if spec["kind"] == "pasal" else split_sections(text)
        for number, article_number, content in pieces:
            record = build_record(spec, number, article_number, content)
            if record["rule_id"] in seen:
                raise ValueError(f"duplicate rule_id {record['rule_id']}")
            seen.add(record["rule_id"])
            grouped[spec["country"]].append(record)
    return grouped


def main() -> int:
    grouped = extract()
    outputs = {
        "ID": BASE / "data" / "ID" / "statute_articles.json",
        "MY": BASE / "data" / "MY" / "statute_articles.json",
    }
    summary = {}
    for country, records in grouped.items():
        path = outputs[country]
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary[country] = len(records)
        print(f"{country}: {len(records)} -> {path.relative_to(BASE)}")
    print(f"total {sum(summary.values())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
