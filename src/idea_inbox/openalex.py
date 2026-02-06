from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


OPENALEX_WORKS = "https://api.openalex.org/works"


@dataclass
class Ref:
    title: str
    year: int | None
    venue: str | None
    doi: str | None
    url: str | None
    authors: list[str]
    type: str | None


def _get(obj: dict[str, Any], path: str, default=None):
    cur: Any = obj
    for part in path.split("."):
        if cur is None:
            return default
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return default
    return cur if cur is not None else default


def search(query: str, per_page: int = 10, mailto: str | None = None) -> list[Ref]:
    params = {
        "search": query,
        "per-page": str(per_page),
    }
    if mailto:
        params["mailto"] = mailto

    url = OPENALEX_WORKS + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "idea-inbox/0.1"})

    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)

    out: list[Ref] = []
    for w in data.get("results", []):
        title = (w.get("title") or "").strip()
        if not title:
            continue
        year = w.get("publication_year")
        venue = _get(w, "host_venue.display_name")
        doi = w.get("doi")
        url2 = _get(w, "primary_location.landing_page_url") or _get(w, "primary_location.source.homepage_url")

        authors: list[str] = []
        for a in w.get("authorships", [])[:5]:
            name = _get(a, "author.display_name")
            if name:
                authors.append(name)

        out.append(
            Ref(
                title=title,
                year=year,
                venue=venue,
                doi=doi,
                url=url2,
                authors=authors,
                type=w.get("type"),
            )
        )

    return out
