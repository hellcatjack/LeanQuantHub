# Contributing (English Companion)

> This is the English companion of `CONTRIBUTING.md`.

## Branch & Commit
1. Branch naming: `feature/<topic>` or `fix/<topic>`
2. Commit prefixes: `feat:` / `fix:` / `docs:` / `chore:`
3. Ensure `.env`, data directories, and build artifacts are not tracked

## Local Verification
- Frontend: `npm run dev`, ensure core pages are accessible
- Backend: `uvicorn app.main:app --host 0.0.0.0 --port 8021`
- Backtest: trigger from UI or `/api/backtests`, verify status and report generation

## Documentation Updates
When environment variables, deployment, or algorithm parameters change, update:
- `README.md`
- `backend/.env.example`
- `frontend/.env.example`
