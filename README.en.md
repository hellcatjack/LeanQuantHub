# LeanQuantHub (English Companion)

> This is the English companion of `README.md`. It is a full translation; refer to the Chinese version as the primary document.

This project is for quantitative trading learning and research and does not constitute any investment advice.

LeanQuantHub is a localized, multi-user quantitative platform: the frontend follows a QuantConnect-style experience, and the backend uses a Lean Runner task execution model. It supports theme management, data management, backtests, and report archiving.

## Repository Structure
- `backend/`: FastAPI + MySQL metadata service
- `frontend/`: React + Vite frontend
- `algorithms/`: Lean algorithm scripts
- `ml/`: ML scoring and inference utilities
- `configs/`: Lean config templates and theme weights
- `deploy/`: systemd services and deployment scripts

## Documentation Index
- Docs overview: `docs/README.md`
- Data sources: `docs/data_sources/README.md`
- Reports: `docs/reports/README.md`
- TODO lists: `docs/todolists/README.md`

## Local Development
> Run build/serve commands inside `backend/` or `frontend/`, not in the repo root.

### Backend
```bash
cd /app/stocklean
cp backend/.env.example backend/.env
# Fill DB_* / LEAN_* / ML_* env vars
python3.11 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt -r ml/requirements.txt
cd backend
../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8021
```

### Frontend
```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Default frontend: http://localhost:5173  
Default backend: http://localhost:8021

## Server Deployment (systemd)
```bash
cd frontend
npm install
npm run build

# Deploy systemd user services
cp deploy/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart stocklean-backend stocklean-frontend
```

Default frontend: http://<host>:8081  
Default backend: http://<host>:8021

## Lean Runner Configuration
Set in backend `.env`:
- `LEAN_LAUNCHER_PATH`: Lean Launcher csproj
- `LEAN_CONFIG_TEMPLATE`: Lean config template JSON
- `LEAN_ALGORITHM_PATH`: algorithm script path
- `LEAN_DATA_FOLDER`: Lean data directory
- `LEAN_PYTHON_VENV`: unified Python 3.11 venv (recommended `/app/stocklean/.venv`)
- `PYTHON_DLL`: Python 3.11 `libpython` path (recommended `/app/stocklean/.venv/lib/libpython3.11.so`)
- `DOTNET_PATH` / `DOTNET_ROOT`

## Data & Lifecycle Overrides
Backtests use `data_root/universe/alpha_symbol_life.csv` for IPO/delist dates. If Alpha’s `delistingDate` conflicts with price history, an override file can be used:
- Default path: `data_root/universe/symbol_life_override.csv`
- Format: `symbol,ipoDate,delistingDate,source,note`
- Priority: `symbol_life_override.csv` > `alpha_symbol_life.csv`
- Custom path via `symbol_life_override_path`

## Data Sources
- Directory: `docs/data_sources/`
- Implemented: Alpha Vantage (`docs/data_sources/alpha.md`)

## TODO List Conventions
- Directory: `docs/todolists/`
- Naming: `<Topic>TODO.md` / `<Topic>TestTODO.md`
- No TODO files in repo root
- Index: `docs/todolists/README.md`

## Report Archive
- Backtest reports: `docs/reports/backtests/`
- ML training comparisons: `docs/reports/ml/`

## ML Scoring (Unified venv)
- Lean and ML use Python 3.11 (Python.NET compatible)
- Set in `.env`:
  - `ML_PYTHON_PATH=/app/stocklean/.venv/bin/python`

## Security & Contributions
- Do not commit `.env`, data directories, logs, or build artifacts
- Use `.env.example` as template; never expose secrets or internal addresses
