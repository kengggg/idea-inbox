from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


def _get(obj: dict[str, Any], key: str, default=None):
    v = obj.get(key)
    return default if v is None else v


@dataclass
class WikiResult:
    title: str
    url: str
    extract: str | None = None


def search(query: str, limit: int = 5) -> list[WikiResult]:
    """Return candidate Wikipedia pages for a query.

    Uses MediaWiki API (en.wikipedia.org).
    """
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "utf8": "1",
        "srlimit": str(limit),
    }
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "idea-inbox/0.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results: list[WikiResult] = []
    for item in _get(_get(data, "query", {}), "search", []) or []:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        page_url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        results.append(WikiResult(title=title, url=page_url))
    return results


def summary(title: str) -> WikiResult:
    """Fetch a short summary for a title (REST API)."""
    t = title.replace(" ", "_")
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(t)
    req = urllib.request.Request(url, headers={"User-Agent": "idea-inbox/0.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    page_title = (data.get("title") or title).strip()
    extract = (data.get("extract") or "").strip() or None
    page_url = None
    content_urls = data.get("content_urls") or {}
    desktop = content_urls.get("desktop") or {}
    page_url = desktop.get("page")
    if not page_url:
        page_url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page_title.replace(" ", "_"))

    return WikiResult(title=page_title, url=page_url, extract=extract)
