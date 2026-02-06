# idea-inbox

Telegram `/idea` capture flow → Obsidian vault.

## Repo roles

- Dev lives in: `/home/keng/workspaces/idea-inbox`
- Vault lives in: `/home/keng/vault` (ideas in `vault/ideas/`)
- Deployed snapshot (later): `/home/keng/apps/idea-inbox` (read-only)

## v1 behavior

- Send `/idea` in Telegram
- Bot asks for the idea
- Your next message is saved as a markdown file in `~/vault/ideas/`
- `/cancel` aborts a pending capture
- Pending capture times out after 2 minutes (silent)

See `REQUIREMENTS.md`.
