#!/usr/bin/env python3
"""idea-inbox CLI.

This CLI is designed to be invoked by the OpenClaw agent via `exec`.
It maintains a tiny pending-capture state and writes Obsidian-compatible
Markdown files into the vault.

State (v1): ./state/state.json (project-local)
Vault (v1 default): ~/vault/ideas

Commands:
  start         - start a pending capture (with expiry)
  cancel        - cancel pending capture
  status        - print capture + enrichment status (for debugging)
  commit        - if pending, write an idea markdown file and clear pending
  enrich-start  - start enrichment follow-up (clarifier) pending
  enrich-cancel - cancel enrichment follow-up pending
  refs          - fetch top references from OpenAlex for a query (JSON)
  append        - append markdown to an existing idea file

All outputs are line-oriented for easy agent parsing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from idea_inbox.openalex import search as openalex_search


DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_VAULT_DIR = Path.home() / "vault"
DEFAULT_IDEAS_DIR = DEFAULT_VAULT_DIR / "ideas"


def now_local() -> datetime:
    # Local time with tz info if available
    return datetime.now().astimezone()


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def slugify(s: str, max_len: int = 60) -> str:
    s = s.strip().lower()
    # keep alnum, spaces, dash/underscore
    s = re.sub(r"[^a-z0-9\s_-]+", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        return "idea"
    return s[:max_len].strip("-")


@dataclass
class State:
    # capture wizard
    pending: bool = False
    pending_until: str | None = None  # ISO string
    started_at: str | None = None
    user_id: str | None = None

    # last committed idea (for enrichment linkage)
    last_file: str | None = None
    last_idea_text: str | None = None

    # enrichment follow-up wizard
    enrich_pending: bool = False
    enrich_until: str | None = None
    enrich_user_id: str | None = None
    enrich_file: str | None = None
    enrich_idea_text: str | None = None

    @staticmethod
    def load(path: Path) -> "State":
        if not path.exists():
            return State()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return State()
        return State(
            pending=bool(data.get("pending", False)),
            pending_until=data.get("pending_until"),
            started_at=data.get("started_at"),
            user_id=data.get("user_id"),
            last_file=data.get("last_file"),
            last_idea_text=data.get("last_idea_text"),
            enrich_pending=bool(data.get("enrich_pending", False)),
            enrich_until=data.get("enrich_until"),
            enrich_user_id=data.get("enrich_user_id"),
            enrich_file=data.get("enrich_file"),
            enrich_idea_text=data.get("enrich_idea_text"),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "pending": self.pending,
                    "pending_until": self.pending_until,
                    "started_at": self.started_at,
                    "user_id": self.user_id,
                    "last_file": self.last_file,
                    "last_idea_text": self.last_idea_text,
                    "enrich_pending": self.enrich_pending,
                    "enrich_until": self.enrich_until,
                    "enrich_user_id": self.enrich_user_id,
                    "enrich_file": self.enrich_file,
                    "enrich_idea_text": self.enrich_idea_text,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def is_expired(self, at: datetime) -> bool:
        if not self.pending or not self.pending_until:
            return False
        try:
            until = datetime.fromisoformat(self.pending_until)
        except Exception:
            return True
        return at >= until

    def enrich_is_expired(self, at: datetime) -> bool:
        if not self.enrich_pending or not self.enrich_until:
            return False
        try:
            until = datetime.fromisoformat(self.enrich_until)
        except Exception:
            return True
        return at >= until


def ensure_not_expired(state: State, at: datetime) -> State:
    if state.pending and state.is_expired(at):
        state.pending = False
        state.pending_until = None
        state.started_at = None
        state.user_id = None

    if state.enrich_pending and state.enrich_is_expired(at):
        state.enrich_pending = False
        state.enrich_until = None
        state.enrich_user_id = None
        state.enrich_file = None
        state.enrich_idea_text = None

    return state


def cmd_start(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    state = ensure_not_expired(State.load(state_path), now_local())

    # restart window if already pending
    started = now_local()
    until = started + timedelta(seconds=args.timeout)

    state.pending = True
    state.started_at = iso(started)
    state.pending_until = iso(until)
    state.user_id = args.user_id
    state.save(state_path)

    print(f"OK pending_until={state.pending_until}")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    """Cancel any pending interactive flow.

    In v1.1 we treat `/cancel` as a universal cancel for both:
    - idea capture pending
    - enrichment clarifier pending
    """
    state_path = Path(args.state)
    state = ensure_not_expired(State.load(state_path), now_local())

    had_any = state.pending or state.enrich_pending

    # capture
    state.pending = False
    state.pending_until = None
    state.started_at = None
    state.user_id = None

    # enrichment follow-up
    state.enrich_pending = False
    state.enrich_until = None
    state.enrich_user_id = None
    state.enrich_file = None
    state.enrich_idea_text = None

    state.save(state_path)

    if not had_any:
        print("OK no_pending")
    else:
        print("OK cancelled")
    return 0


def cmd_enrich_start(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    state = ensure_not_expired(State.load(state_path), now_local())

    started = now_local()
    until = started + timedelta(seconds=args.timeout)

    state.enrich_pending = True
    state.enrich_until = iso(until)
    state.enrich_user_id = args.user_id
    state.enrich_file = args.file
    state.enrich_idea_text = args.idea_text
    state.save(state_path)

    print(f"OK enrich_pending_until={state.enrich_until}")
    return 0


def cmd_enrich_cancel(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    state = ensure_not_expired(State.load(state_path), now_local())
    if not state.enrich_pending:
        print("OK no_enrich_pending")
        return 0
    state.enrich_pending = False
    state.enrich_until = None
    state.enrich_user_id = None
    state.enrich_file = None
    state.enrich_idea_text = None
    state.save(state_path)
    print("OK enrich_cancelled")
    return 0


def cmd_refs(args: argparse.Namespace) -> int:
    # Fetch and print JSON refs (agent will format + add relevance text)
    refs = openalex_search(
        args.query,
        per_page=max(10, args.limit * 3),
        mailto=args.mailto,
        sort=args.sort,
        from_year=args.from_year,
    )

    # basic filtering: keep works with a venue OR a DOI/URL, and avoid obvious books
    filtered = []
    for r in refs:
        if r.type in ("book", "book-chapter"):
            continue
        if not (r.doi or r.url or r.venue):
            continue
        filtered.append(r)

    out = []
    for r in filtered[: args.limit]:
        out.append(
            {
                "title": r.title,
                "year": r.year,
                "venue": r.venue,
                "doi": r.doi,
                "url": r.url,
                "authors": r.authors,
                "type": r.type,
            }
        )

    print(json.dumps({"query": args.query, "count": len(out), "refs": out}, ensure_ascii=False))
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    path = Path(args.file).expanduser()
    if not path.exists():
        print("ERR file_not_found")
        return 2
    content = args.markdown
    # Ensure a newline before appending
    existing = path.read_text(encoding="utf-8")
    sep = "\n" if not existing.endswith("\n") else ""
    path.write_text(existing + sep + content.rstrip() + "\n", encoding="utf-8")
    print("OK appended")
    print(f"FILE {path}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    state = ensure_not_expired(State.load(state_path), now_local())
    # Persist expiry cleanup if needed
    state.save(state_path)

    print(f"CAPTURE_PENDING {str(state.pending).lower()}")
    if state.pending:
        print(f"CAPTURE_STARTED_AT {state.started_at}")
        print(f"CAPTURE_PENDING_UNTIL {state.pending_until}")
        print(f"CAPTURE_USER_ID {state.user_id}")

    print(f"ENRICH_PENDING {str(state.enrich_pending).lower()}")
    if state.enrich_pending:
        print(f"ENRICH_PENDING_UNTIL {state.enrich_until}")
        print(f"ENRICH_USER_ID {state.enrich_user_id}")
        print(f"ENRICH_FILE {state.enrich_file}")

    if state.last_file:
        print(f"LAST_FILE {state.last_file}")
    if state.last_idea_text:
        print(f"LAST_IDEA_LEN {len(state.last_idea_text)}")

    return 0


def build_markdown(created: datetime, user_id: str, text: str, idea_id: str) -> str:
    # Minimal v1 frontmatter
    fm = [
        "---",
        f"id: {idea_id}",
        f"created: {iso(created)}",
        "source: telegram",
        "type: idea",
        f"telegram_user_id: {user_id}",
        "---",
        "",
    ]
    body = text.rstrip() + "\n"
    return "\n".join(fm) + body


def cmd_commit(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    state = ensure_not_expired(State.load(state_path), now_local())

    if not state.pending:
        print("ERR not_pending")
        return 2

    if state.user_id and args.user_id and state.user_id != args.user_id:
        print("ERR wrong_user")
        return 3

    created = now_local()
    text = args.text
    title_basis = text.strip().splitlines()[0] if text.strip() else "idea"
    slug = slugify(title_basis)

    filename = f"{created.strftime('%Y-%m-%d_%H%M%S')}_{slug}.md"
    ideas_dir = Path(args.ideas_dir).expanduser()
    ideas_dir.mkdir(parents=True, exist_ok=True)

    # unique ID: ISO + random-ish suffix from time
    idea_id = f"{iso(created)}-{created.strftime('%f')}"

    out_path = ideas_dir / filename
    out_path.write_text(build_markdown(created, args.user_id, text, idea_id), encoding="utf-8")

    # clear capture pending
    state.pending = False
    state.pending_until = None
    state.started_at = None
    state.user_id = None

    # remember last idea for enrichment
    state.last_file = str(out_path)
    state.last_idea_text = text

    state.save(state_path)

    print("OK saved")
    print(f"FILE {out_path}")
    print(f"TITLE {title_basis.strip()[:120]}")
    return 0


def _extract_global_flags(argv: list[str]) -> tuple[dict[str, str], list[str]]:
    """Allow --state/--ideas-dir anywhere in argv (before or after subcommand).

    This is mainly to make agent tool calls less fragile.
    """
    out: dict[str, str] = {}
    rest: list[str] = []
    it = iter(range(len(argv)))
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--state", "--ideas-dir") and i + 1 < len(argv):
            out[a.lstrip("-").replace("-", "_")] = argv[i + 1]
            i += 2
            continue
        rest.append(a)
        i += 1
    return out, rest


def main(argv: list[str]) -> int:
    extracted, argv2 = _extract_global_flags(argv)

    p = argparse.ArgumentParser(prog="idea-inbox")
    p.add_argument(
        "--state",
        default=extracted.get(
            "state", str(Path(__file__).resolve().parents[2] / "state" / "state.json")
        ),
        help="Path to state JSON file",
    )
    p.add_argument(
        "--ideas-dir",
        default=extracted.get("ideas_dir", str(DEFAULT_IDEAS_DIR)),
        help="Directory to write idea markdown files",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("start")
    ps.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    ps.add_argument("--user-id", required=True)
    ps.set_defaults(func=cmd_start)

    pc = sub.add_parser("cancel")
    pc.set_defaults(func=cmd_cancel)

    pst = sub.add_parser("status")
    pst.set_defaults(func=cmd_status)

    pm = sub.add_parser("commit")
    pm.add_argument("--user-id", required=True)
    pm.add_argument("--text", required=True)
    pm.set_defaults(func=cmd_commit)

    pe = sub.add_parser("enrich-start")
    pe.add_argument("--user-id", required=True)
    pe.add_argument("--file", required=True)
    pe.add_argument("--idea-text", required=True)
    pe.add_argument("--timeout", type=int, default=120)
    pe.set_defaults(func=cmd_enrich_start)

    pec = sub.add_parser("enrich-cancel")
    pec.set_defaults(func=cmd_enrich_cancel)

    pr = sub.add_parser("refs")
    pr.add_argument("--query", required=True)
    pr.add_argument("--limit", type=int, default=5)
    pr.add_argument("--mailto", default=None)
    pr.add_argument(
        "--sort",
        default=None,
        help='OpenAlex sort, e.g. "publication_date:desc"',
    )
    pr.add_argument(
        "--from-year",
        type=int,
        default=None,
        help="Filter to works published from this year (inclusive)",
    )
    pr.set_defaults(func=cmd_refs)

    pa = sub.add_parser("append")
    pa.add_argument("--file", required=True)
    pa.add_argument("--markdown", required=True)
    pa.set_defaults(func=cmd_append)

    args = p.parse_args(argv2)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
