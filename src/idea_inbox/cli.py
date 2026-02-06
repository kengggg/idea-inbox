#!/usr/bin/env python3
"""idea-inbox CLI.

This CLI is designed to be invoked by the OpenClaw agent via `exec`.
It maintains a tiny pending-capture state and writes Obsidian-compatible
Markdown files into the vault.

State (v1): ./state/state.json (project-local)
Vault (v1 default): ~/vault/ideas

Commands:
  start   - start a pending capture (with expiry)
  cancel  - cancel pending capture
  status  - print pending status (for debugging)
  commit  - if pending, write an idea markdown file and clear pending

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
    pending: bool = False
    pending_until: str | None = None  # ISO string
    started_at: str | None = None
    user_id: str | None = None

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


def ensure_not_expired(state: State, at: datetime) -> State:
    if state.pending and state.is_expired(at):
        state.pending = False
        state.pending_until = None
        state.started_at = None
        state.user_id = None
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
    state_path = Path(args.state)
    state = State.load(state_path)
    if not state.pending:
        print("OK no_pending")
        return 0
    state.pending = False
    state.pending_until = None
    state.started_at = None
    state.user_id = None
    state.save(state_path)
    print("OK cancelled")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state_path = Path(args.state)
    state = ensure_not_expired(State.load(state_path), now_local())
    # Persist expiry cleanup if needed
    state.save(state_path)
    if not state.pending:
        print("PENDING false")
        return 0
    print("PENDING true")
    print(f"STARTED_AT {state.started_at}")
    print(f"PENDING_UNTIL {state.pending_until}")
    print(f"USER_ID {state.user_id}")
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

    # clear pending
    state.pending = False
    state.pending_until = None
    state.started_at = None
    state.user_id = None
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

    args = p.parse_args(argv2)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
