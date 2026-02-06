# Idea Inbox → Obsidian Vault (v1) Requirements

## 0) Scope (v1)
- Text-only idea capture in Telegram via a guided flow started by `/idea`.
- Store ideas locally as Obsidian-compatible Markdown files.
- Confirm save + provide a way to cancel.
- No voice transcription yet.
- No retrieval/search commands yet (future v2).

## 1) Workspace / directory conventions (important)

### 1.1 Dev vs deployed separation
We intentionally separate *active development* from the *deployed, stable runtime*.

- **Dev / iteration (writable):** `./workspaces/idea-inbox/`
  - This is where we build, experiment, test, and change things.
- **Deployed app (read-only):** `./apps/idea-inbox/`
  - This is treated as immutable runtime.
  - Updates happen only via a deliberate **promote/deploy** step.

### 1.2 Vault (shared data)
- **Obsidian vault root:** `./vault/`
- **Idea storage:** `./vault/ideas/`

The vault is *not* inside the app/project repo. Other projects may also write into `./vault/` later.

### 1.3 State
- Maintain a small local state store for the `/idea` pending-capture wizard.
- **State must be part of the project** and writable.
- v1 path:
  - `./workspaces/idea-inbox/state/state.json`

Requirement: state must survive restarts and must not cause accidental captures.

## 2) User experience (Telegram)

### 2.1 Start capture
- **Trigger:** user sends `/idea`
- Bot replies:
  - “What’s the idea?”
  - Hint: “Send one message. `/cancel` to abort.”

### 2.2 Capture content
- The **next single message** from the same user is recorded as the idea body.
- Only one message is captured (single-shot) to avoid ambiguity.

### 2.3 Confirm saved
After saving, bot replies with:
- “Saved idea”
- Title (auto-derived from first line or first ~8–12 words)
- Filename (and optionally relative path) for transparency

### 2.4 Cancel / timeout
- If user sends `/cancel` while capture is pending → abort and confirm “Cancelled.”
- Pending capture expires after **2 minutes**.
  - On expiry, subsequent messages are treated as normal chat.
  - Expiry notice behavior: **silent** by default (can be changed later).

### 2.5 Safety: never capture by accident
- If there is **no pending `/idea` session**, nothing is captured.
- Only the authorized Telegram user id (`524235135`) can use `/idea` (DM pairing already gates access; still enforce in code).

## 3) Storage format (Obsidian Markdown)

### 3.1 One idea = one file
- One idea is stored as exactly one markdown file.

### 3.2 File naming
- Filename format:
  - `YYYY-MM-DD_HHMMSS_<slug>.md`
- Example:
  - `2026-02-06_1344_timelapse-pipeline.md`

### 3.3 File contents
Each idea file contains:
- YAML frontmatter:
  - `id` (unique)
  - `created` (ISO timestamp with timezone)
  - `source: telegram`
  - `type: idea`
- Body: captured text as sent (minimal normalization)

Example:

```md
---
id: 2026-02-06T13:44:12+07:00-0001
created: 2026-02-06T13:44:12+07:00
source: telegram
type: idea
---
<idea text>
```

### 3.4 Git hygiene
- `./vault/` is treated as data and should not be committed to the app repo unless explicitly desired.
- The idea-inbox repo should include a `.gitignore` that prevents accidental committing of vault contents.

## 4) Deployment / promotion (no daemon in v1)

### 4.1 Runtime model
- v1 runs inside the OpenClaw agent process (no separate background daemon required).

### 4.2 Promote/deploy process
- “Deploy” means copying a known-good snapshot from `./workspaces/idea-inbox/` → `./apps/idea-inbox/`.
- After promotion, enforce read-only on the deployed directory:
  - `chmod -R a-w ./apps/idea-inbox`

Notes:
- Updates are done by promoting a new snapshot (optionally clearing/recreating the target dir).
- If needed, temporarily unlock with `chmod -R u+w` during promotion, then lock again.

## 5) Non-goals (explicitly NOT in v1)
- Voice memo transcription
- Multi-message capture sessions
- Automatic topic taxonomy + backlink pages
- Full semantic search / embeddings
- Sync to iCloud/Dropbox
- GitHub publishing of vault contents

## 6) Done criteria (v1 “ship it”)
- `/idea` → prompt → next message saved to `./vault/ideas/…md`
- `/cancel` works
- Expiry works (2 min)
- Confirmation message includes filename
- 5–10 manual tests in DM with no accidental captures
