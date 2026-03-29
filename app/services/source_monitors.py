from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import MonitoredSource
from app.services.hashing import sha256_bytes, sha256_text
from app.services.ingestion import ingest_supported_bytes_as_update, record_artifact, utcnow

logger = logging.getLogger(__name__)

DATE_RE = re.compile(r"\d{2}[/-]\d{2}[/-]\d{4}")
DATE_TEXT_RE = re.compile(r"\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4}", re.IGNORECASE)
CIRCULAR_RE = re.compile(r"circulaire\s*(?:n\s*[°º]\s*)?(\d{1,2}\s*/\s*20\d{2})", re.IGNORECASE)
SPOT_MODIFIED_RE = re.compile(
    r"modifi(?:é|e)\s*(?:le)?\s*[:\-]?\s*(\d{1,2}\s+[A-Za-zÀ-ÿ]+\s+\d{4}|\d{2}[/-]\d{2}[/-]\d{4})",
    re.IGNORECASE,
)
CNAM_VEI_RE = re.compile(
    r"vei\s*\((?:mise\s*à\s*jour|mise\s*a\s*jour)\s*(?:le)?\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})\)",
    re.IGNORECASE,
)
DPM_UPDATE_RE = re.compile(r"date\s+de\s+mise\s+à\s+jour\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4})", re.IGNORECASE)


@dataclass
class SourceDiscovery:
    source_name: str
    source_url: str
    latest_marker: str | None
    latest_title: str | None
    latest_item_url: str | None
    effective_date_text: str | None
    parser_hint: str | None = None
    kind: str = "page"
    requires_review: bool = False


SOURCES: list[SourceDiscovery] = [
    SourceDiscovery(
        source_name="spot_circulars",
        source_url="https://www.spot.tn/?mayor=articles&type=cir",
        latest_marker=None,
        latest_title=None,
        latest_item_url=None,
        effective_date_text=None,
        parser_hint=None,
        kind="page",
        requires_review=True,
    ),
    SourceDiscovery(
        source_name="pct_circulars",
        source_url="https://www.phct.com.tn/index.php/communiques/circulaires-de-la-pct/list/57",
        latest_marker=None,
        latest_title=None,
        latest_item_url=None,
        effective_date_text=None,
        parser_hint=None,
        kind="page",
        requires_review=True,
    ),
    SourceDiscovery(
        source_name="spot_vei",
        source_url="https://spot.tn/?id=337&mayor=articles",
        latest_marker=None,
        latest_title=None,
        latest_item_url=None,
        effective_date_text=None,
        parser_hint="vei",
        kind="page",
    ),
    SourceDiscovery(
        source_name="cnam_vei",
        source_url="https://www.cnam.nat.tn/espace_ps.jsp",
        latest_marker=None,
        latest_title=None,
        latest_item_url=None,
        effective_date_text=None,
        parser_hint="vei",
        kind="page",
    ),
    SourceDiscovery(
        source_name="dpm_human_medicines",
        source_url="https://dpm.tn/medicament/humain/liste-des-medicaments",
        latest_marker=None,
        latest_title=None,
        latest_item_url=None,
        effective_date_text=None,
        parser_hint=None,
        kind="page",
        requires_review=True,
    ),
]


async def fetch_url(url: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=40, follow_redirects=True, headers={"User-Agent": settings.http_user_agent}) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return " ".join(text.split())


def _extract_date(text: str) -> str | None:
    normalized = _normalize_text(text)
    match = DATE_RE.search(normalized)
    if match:
        return match.group(0)
    match = DATE_TEXT_RE.search(normalized)
    if match:
        return match.group(0)
    return None


def _find_first_link_by_keywords(soup: BeautifulSoup, keywords: list[str], base_url: str) -> tuple[str | None, str | None]:
    lowered_keywords = [_normalize_text(k).lower() for k in keywords]
    for anchor in soup.find_all("a", href=True):
        text = _normalize_text(anchor.get_text(" ", strip=True))
        href = anchor["href"]
        full_url = urljoin(base_url, href)
        text_lower = text.lower()
        href_lower = href.lower()
        if any(keyword in text_lower or keyword in href_lower for keyword in lowered_keywords):
            return text or None, full_url
    return None, None


def _best_link_for_container(container: Tag, base_url: str) -> tuple[str | None, str | None]:
    anchors = container.find_all("a", href=True)
    if not anchors:
        return None, None

    preferred_anchor = None
    generic_anchor = None
    for anchor in anchors:
        text = _normalize_text(anchor.get_text(" ", strip=True))
        href = anchor["href"]
        href_lower = href.lower()
        if any(token in href_lower for token in (".pdf", ".xls", ".xlsx", ".csv", ".json")):
            preferred_anchor = anchor
            break
        if text and text.lower() not in {"voir plus", "lire plus", "more", "details"} and len(text) > 5:
            preferred_anchor = anchor
            break
        if generic_anchor is None:
            generic_anchor = anchor

    anchor = preferred_anchor or generic_anchor
    if anchor is None:
        return None, None
    return _normalize_text(anchor.get_text(" ", strip=True)) or None, urljoin(base_url, anchor["href"])


def _find_first_article_with_marker(soup: BeautifulSoup, pattern: re.Pattern[str], base_url: str) -> tuple[str | None, str | None]:
    containers = soup.find_all(["article", "li", "div", "tr", "section"])
    for container in containers:
        text = _normalize_text(container.get_text(" ", strip=True))
        if not text or not pattern.search(text):
            continue
        anchor_text, item_url = _best_link_for_container(container, base_url)
        return (text if text else anchor_text), item_url
    return None, None


def discover_source(source_name: str, url: str, html: str) -> SourceDiscovery:
    soup = BeautifulSoup(html, "html.parser")
    page_text = _normalize_text(soup.get_text(" ", strip=True))

    if source_name == "spot_circulars":
        title, item_url = _find_first_article_with_marker(soup, CIRCULAR_RE, url)
        marker_match = CIRCULAR_RE.search(title or page_text)
        effective_date = _extract_date(title or page_text)
        marker = marker_match.group(1).replace(" ", "") if marker_match else effective_date
        return SourceDiscovery(source_name, url, marker, title, item_url, effective_date, None, "page", True)

    if source_name == "pct_circulars":
        title, item_url = _find_first_article_with_marker(soup, CIRCULAR_RE, url)
        marker_match = CIRCULAR_RE.search(title or page_text)
        effective_date = _extract_date(title or page_text)
        marker = marker_match.group(1).replace(" ", "") if marker_match else effective_date
        return SourceDiscovery(source_name, url, marker, title, item_url, effective_date, None, "page", True)

    if source_name == "spot_vei":
        modified_match = SPOT_MODIFIED_RE.search(page_text)
        title, item_url = _find_first_link_by_keywords(soup, ["VEI", "médicaments classes en VEI", ".xls", ".xlsx"], url)
        marker = modified_match.group(1) if modified_match else _extract_date(page_text)
        return SourceDiscovery(source_name, url, marker, title or "Liste VEI", item_url, marker, "vei", "page", False)

    if source_name == "cnam_vei":
        marker_match = CNAM_VEI_RE.search(page_text)
        title, item_url = _find_first_link_by_keywords(soup, ["VEI", ".xls", ".xlsx"], url)
        marker = marker_match.group(1) if marker_match else _extract_date(page_text)
        return SourceDiscovery(source_name, url, marker, title or "CNAM VEI", item_url, marker, "vei", "page", False)

    if source_name == "dpm_human_medicines":
        marker_match = DPM_UPDATE_RE.search(page_text)
        title, item_url = _find_first_link_by_keywords(soup, ["Liste des médicaments", "AMM", ".xls", ".xlsx", ".pdf"], url)
        marker = marker_match.group(1) if marker_match else _extract_date(page_text)
        return SourceDiscovery(source_name, url, marker, title or "DPM médicaments à usage humain", item_url, marker, None, "page", True)

    return SourceDiscovery(source_name, url, None, None, None, None, None, "page", True)


async def _download_latest_item(discovery: SourceDiscovery) -> tuple[bytes | None, str | None, str | None]:
    if not settings.auto_download_official_files or not discovery.latest_item_url:
        return None, None, None
    try:
        response = await fetch_url(discovery.latest_item_url)
        content_type = response.headers.get("content-type")
        filename = discovery.latest_item_url.rstrip("/").split("/")[-1] or f"{discovery.source_name}.bin"
        return response.content, content_type, filename
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to download latest item for %s: %s", discovery.source_name, exc)
        return None, None, None


def _upsert_source_state(db: Session, discovery: SourceDiscovery, page_hash: str, item_hash: str | None, status: str, error: str | None = None) -> tuple[MonitoredSource, bool]:
    state = db.execute(select(MonitoredSource).where(MonitoredSource.source_name == discovery.source_name)).scalar_one_or_none()
    is_changed = False
    now = utcnow()

    if state is None:
        state = MonitoredSource(
            source_name=discovery.source_name,
            source_url=discovery.source_url,
            latest_marker=discovery.latest_marker,
            latest_title=discovery.latest_title,
            latest_item_url=discovery.latest_item_url,
            last_page_hash=page_hash,
            last_item_hash=item_hash,
            status=status,
            error=error,
            requires_review=discovery.requires_review,
            last_checked_at=now,
            last_changed_at=now,
        )
        db.add(state)
        is_changed = True
    else:
        is_changed = any(
            [
                state.latest_marker != discovery.latest_marker,
                state.latest_item_url != discovery.latest_item_url,
                state.last_page_hash != page_hash,
                item_hash is not None and state.last_item_hash != item_hash,
            ]
        )
        state.source_url = discovery.source_url
        state.latest_marker = discovery.latest_marker
        state.latest_title = discovery.latest_title
        state.latest_item_url = discovery.latest_item_url
        state.last_page_hash = page_hash
        if item_hash is not None:
            state.last_item_hash = item_hash
        state.status = status
        state.error = error
        state.requires_review = discovery.requires_review
        state.last_checked_at = now
        if is_changed:
            state.last_changed_at = now

    db.commit()
    db.refresh(state)
    return state, is_changed


async def check_single_source(db: Session, source_name: str) -> dict[str, Any]:
    source_def = next((source for source in SOURCES if source.source_name == source_name), None)
    if source_def is None:
        raise ValueError(f"Unknown source: {source_name}")

    try:
        page_response = await fetch_url(source_def.source_url)
        html = page_response.text
        discovery = discover_source(source_def.source_name, source_def.source_url, html)
        page_hash = sha256_text(html)

        item_content, item_content_type, item_filename = await _download_latest_item(discovery)
        item_hash = sha256_bytes(item_content) if item_content else None

        state, changed = _upsert_source_state(db, discovery, page_hash, item_hash, status="ok")

        artifact_info: dict[str, Any] | None = None
        if changed:
            page_artifact = record_artifact(
                db,
                source_name=discovery.source_name,
                title=discovery.latest_title or f"{discovery.source_name} landing page",
                origin_url=discovery.source_url,
                path=f"{discovery.source_name}.html",
                content=html.encode("utf-8"),
                content_type=page_response.headers.get("content-type"),
                parser_hint=None,
                kind="source_page",
                monitored_source_id=state.id,
                marker=discovery.latest_marker,
                effective_date_text=discovery.effective_date_text,
                notes="Landing page snapshot for source monitor",
            )
            artifact_info = {"page_artifact_id": page_artifact.id}

            if item_content and item_filename:
                parse_status = "stored"
                notes = None
                if discovery.parser_hint and settings.auto_ingest_supported_official_files:
                    suffix = item_filename.lower()
                    if suffix.endswith((".json", ".csv", ".xls", ".xlsx")):
                        try:
                            summary = await ingest_supported_bytes_as_update(
                                db,
                                source_name=discovery.source_name,
                                title=discovery.latest_title or item_filename,
                                filename=item_filename,
                                content=item_content,
                                parser_hint=discovery.parser_hint,
                                origin_url=discovery.latest_item_url,
                                marker=discovery.latest_marker,
                                effective_date_text=discovery.effective_date_text,
                                monitored_source_id=state.id,
                                notes="Auto-ingested from official source checker",
                            )
                            parse_status = "parsed"
                            artifact_info["normalized_update"] = summary
                        except Exception as exc:  # pragma: no cover - parser safety
                            parse_status = "review_required"
                            notes = f"Auto-ingest failed: {exc}"
                item_artifact = record_artifact(
                    db,
                    source_name=discovery.source_name,
                    title=discovery.latest_title or item_filename,
                    origin_url=discovery.latest_item_url,
                    path=item_filename,
                    content=item_content,
                    content_type=item_content_type,
                    parser_hint=discovery.parser_hint,
                    kind="source_item",
                    monitored_source_id=state.id,
                    marker=discovery.latest_marker,
                    effective_date_text=discovery.effective_date_text,
                    notes=notes,
                    parse_status=parse_status,
                )
                artifact_info["item_artifact_id"] = item_artifact.id

        return {
            "source_name": source_name,
            "latest_marker": discovery.latest_marker,
            "latest_title": discovery.latest_title,
            "latest_item_url": discovery.latest_item_url,
            "effective_date_text": discovery.effective_date_text,
            "changed": changed,
            "requires_review": discovery.requires_review,
            "artifact_info": artifact_info,
        }
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Source check failed for %s", source_name)
        state, _ = _upsert_source_state(
            db,
            SourceDiscovery(source_name, source_def.source_url, None, None, None, None, source_def.parser_hint, source_def.kind, True),
            page_hash="",
            item_hash=None,
            status="failed",
            error=str(exc),
        )
        return {
            "source_name": source_name,
            "changed": False,
            "status": "failed",
            "error": str(exc),
            "state_id": state.id,
        }


async def check_all_sources(db: Session) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for source in SOURCES:
        results.append(await check_single_source(db, source.source_name))
    return results
