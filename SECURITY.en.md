# Security Notes (English Companion)

> This is the English companion of `SECURITY.md`.

## Secrets
- Do not commit `.env`, keys, passwords, or tokens
- Provide sanitized templates in `.env.example`

## Data & Logs
- Local data/logs are not tracked: `data/`, `logs/`, `artifacts/` are ignored
- If sharing data, anonymize and document source/purpose

## Vulnerability Reporting
Report security issues privately to maintainers. Avoid public disclosure.
