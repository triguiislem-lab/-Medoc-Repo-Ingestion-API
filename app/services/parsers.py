from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup


@dataclass
class NormalizedMedicine:
    dataset: str
    source_key: str
    source_path: str
    code: str | None
    name: str
    dosage: str | None = None
    form: str | None = None
    packaging: str | None = None
    public_price: float | None = None
    reimbursed_price: float | None = None
    manufacturer: str | None = None
    category: str | None = None
    reimbursement_flag: str | None = None
    extra_flag: str | None = None
    raw: dict[str, Any] | list[Any] | str | None = None


@dataclass
class ChangementEntry:
    date_text: str
    title: str
    details: str


@dataclass
class HtmlPageSummary:
    path: str
    title: str | None
    meta_description: str | None
    updated_at_text: str | None
    table_count: int
    source_links: list[str]


DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")
YEAR_RE = re.compile(r"^20\d{2}$")


def parse_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def load_json_rows(raw_text: str) -> list[list[Any]]:
    payload = json.loads(raw_text)
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    if isinstance(payload, list):
        return payload
    raise ValueError("Unsupported JSON dataset shape")


def parse_latest(raw_text: str, source_path: str = "js/latest.json") -> list[NormalizedMedicine]:
    rows = load_json_rows(raw_text)
    items: list[NormalizedMedicine] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            continue
        name, form, dosage, packaging, public_price, reimbursed_price, category = row[:7]
        source_key = "|".join([str(name), str(form), str(dosage), str(packaging)])
        items.append(
            NormalizedMedicine(
                dataset="latest",
                source_key=source_key,
                source_path=source_path,
                code=None,
                name=str(name),
                form=str(form) if form is not None else None,
                dosage=str(dosage) if dosage is not None else None,
                packaging=str(packaging) if packaging is not None else None,
                public_price=parse_price(public_price),
                reimbursed_price=parse_price(reimbursed_price),
                category=str(category) if category is not None else None,
                raw=row,
            )
        )
    return items


def parse_vei(raw_text: str, source_path: str = "js/vei.json") -> list[NormalizedMedicine]:
    rows = load_json_rows(raw_text)
    items: list[NormalizedMedicine] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 7:
            continue
        code, label, public_price, reimbursed_price, reimbursement_flag, category, extra_flag = row[:7]
        source_key = str(code)
        items.append(
            NormalizedMedicine(
                dataset="vei",
                source_key=source_key,
                source_path=source_path,
                code=str(code),
                name=str(label),
                public_price=parse_price(public_price),
                reimbursed_price=parse_price(reimbursed_price),
                category=str(category) if category is not None else None,
                reimbursement_flag=str(reimbursement_flag) if reimbursement_flag is not None else None,
                extra_flag=str(extra_flag) if extra_flag is not None else None,
                raw=row,
            )
        )
    return items


def parse_pct(raw_text: str, source_path: str = "js/pct.json") -> list[NormalizedMedicine]:
    rows = load_json_rows(raw_text)
    items: list[NormalizedMedicine] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            continue
        name, dosage, form, packaging, public_price, category, manufacturer, code = row[:8]
        source_key = str(code)
        items.append(
            NormalizedMedicine(
                dataset="pct",
                source_key=source_key,
                source_path=source_path,
                code=str(code),
                name=str(name),
                dosage=str(dosage) if dosage is not None else None,
                form=str(form) if form is not None else None,
                packaging=str(packaging) if packaging is not None else None,
                public_price=parse_price(public_price),
                manufacturer=str(manufacturer) if manufacturer is not None else None,
                category=str(category) if category is not None else None,
                raw=row,
            )
        )
    return items


def iter_text_nodes(elements: Iterable[Any]) -> Iterable[str]:
    for element in elements:
        text = element.get_text(" ", strip=True)
        if text:
            yield text


def parse_changements(raw_html: str) -> list[ChangementEntry]:
    soup = BeautifulSoup(raw_html, "html.parser")
    texts = list(iter_text_nodes(soup.find_all(["h1", "h2", "h3", "h4", "li", "p", "tr", "td"])))
    entries: list[ChangementEntry] = []
    for index, text in enumerate(texts):
        if DATE_RE.search(text):
            detail = ""
            if index + 1 < len(texts):
                detail = texts[index + 1][:500]
            entries.append(ChangementEntry(date_text=text, title=text, details=detail))
    seen: set[str] = set()
    unique_entries: list[ChangementEntry] = []
    for entry in entries:
        key = entry.title
        if key in seen:
            continue
        seen.add(key)
        unique_entries.append(entry)
    return unique_entries


def parse_html_page_summary(raw_html: str, path: str) -> HtmlPageSummary:
    soup = BeautifulSoup(raw_html, "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else None
    meta_description = None
    description_tag = soup.find("meta", attrs={"name": "description"})
    if description_tag:
        meta_description = description_tag.get("content")

    updated_at_text = None
    for text in iter_text_nodes(soup.find_all(["small", "p", "span", "footer", "div"])):
        if DATE_RE.search(text):
            updated_at_text = text
            break

    source_links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if any(domain in href for domain in ["cnam", "santetunisie", "phct", "dpm", "spot"]):
            source_links.append(href)

    return HtmlPageSummary(
        path=path,
        title=title,
        meta_description=meta_description,
        updated_at_text=updated_at_text,
        table_count=len(soup.find_all("table")),
        source_links=source_links[:20],
    )


def _table_from_bytes(content: bytes, filename: str) -> list[list[Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(StringIO(content.decode("utf-8", errors="replace")), header=None)
    elif suffix in {".xls", ".xlsx"}:
        df = pd.read_excel(BytesIO(content), header=None)
    elif suffix == ".json":
        payload = json.loads(content.decode("utf-8", errors="replace"))
        if isinstance(payload, dict) and isinstance(payload.get("data"), list):
            return payload["data"]
        if isinstance(payload, list):
            return payload
        raise ValueError("Unsupported JSON shape")
    else:
        raise ValueError(f"Unsupported tabular file type: {suffix}")

    rows: list[list[Any]] = []
    for row in df.where(pd.notna(df), None).values.tolist():
        rows.append([cell if cell is None or not isinstance(cell, str) else cell.strip() for cell in row])
    return rows


def _normalize_spreadsheet_rows(rows: list[list[Any]], parser_hint: str) -> list[list[Any]]:
    normalized: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        clean = [cell for cell in row]
        if parser_hint == "vei":
            if len(clean) >= 8 and clean[0] is not None and YEAR_RE.match(str(clean[0]).strip()):
                clean = clean[1:8]
            if len(clean) >= 7 and clean[0] not in (None, "", "Code", "code"):
                normalized.append(clean[:7])
        elif parser_hint == "pct":
            if len(clean) >= 8 and str(clean[0]).strip().lower() not in {"nom", "name"}:
                normalized.append(clean[:8])
        elif parser_hint == "latest":
            if len(clean) >= 7 and str(clean[0]).strip().lower() not in {"nom", "name"}:
                normalized.append(clean[:7])
    return normalized


def parse_supported_uploaded_bytes(content: bytes, filename: str, parser_hint: str, source_path: str) -> list[NormalizedMedicine]:
    parser_hint = parser_hint.lower().strip()
    suffix = Path(filename).suffix.lower()

    if suffix == ".json":
        text = content.decode("utf-8", errors="replace")
        if parser_hint == "vei":
            return parse_vei(text, source_path)
        if parser_hint == "pct":
            return parse_pct(text, source_path)
        if parser_hint == "latest":
            return parse_latest(text, source_path)
        raise ValueError(f"Unsupported parser hint for JSON: {parser_hint}")

    rows = _table_from_bytes(content, filename)
    normalized_rows = _normalize_spreadsheet_rows(rows, parser_hint)
    text = json.dumps({"data": normalized_rows}, ensure_ascii=False)

    if parser_hint == "vei":
        return parse_vei(text, source_path)
    if parser_hint == "pct":
        return parse_pct(text, source_path)
    if parser_hint == "latest":
        return parse_latest(text, source_path)
    raise ValueError(f"Unsupported parser hint: {parser_hint}")
