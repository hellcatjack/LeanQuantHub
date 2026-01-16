# Project Guide (English Companion)

> This is the English companion of `AGENTS.md`. It is a concise summary; refer to the Chinese version for full rules.

## Project Defaults
- Data source is Alpha only; Stooq/Yahoo are disabled.
- Training/backtests use adjusted data under `data_root/curated_adjusted`.

## Run & Build
- Backend: `cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8021`
- Frontend: `cd frontend && npm run dev` / `cd frontend && npm run build`
- systemd: `systemctl --user restart stocklean-backend stocklean-frontend`
- After any frontend UI change, build and restart `stocklean-frontend`.

## Documentation Policy (Bilingual)
- Chinese is the primary document.
- English companion files must use `.en.md` suffix (e.g., `README.en.md`).

## Engineering Rules (Summary)
- Follow Design → Build → Test → Fix → Re-test.
- Provide Plan / Changes / Commands / State Digest in every response.
- Use Playwright for UI verification when applicable.
- DB changes must be scripts in `deploy/mysql/patches/` with idempotency and rollback notes.
- No secrets in repo; use `.env.example` for templates.
- Add progress probes for long-running tasks (training, backtests, sync).
