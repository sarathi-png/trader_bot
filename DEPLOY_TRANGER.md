# DEPLOY_TRANGER.md — Tranger Cloud zip-upload (no credit card)

Target: run the bot on `https://cloud.tranger.xyz` via **zip upload + env
screen**, mock-first, then demo → live. Tranger is Docker-based under the
hood, but you deploy by uploading a zip — no `Dockerfile` or systemd needed.

> Secrets live ONLY in Tranger's env screen. Never put `.env`,
> `sessions/session.json`, or `data/*.db` in the zip.

---

## 0. Before you zip (on your PC)

1. **Rotate the Telegram token**: @BotFather → `/revoke` → new token.
   The old token is burned (it appeared in `logs/bot.log`).
2. Delete local secret/state you will not upload (they stay on your PC):
   keep `.env`, `sessions/`, `data/*.db*`, `logs/` out of the zip.

## 1. Zip manifest

**Include** (source only):
```
run.py  main.py  requirements.txt
auth/  backtest/  config/  core/  database/  engine/  strategies/  tg_bot/
tests/            (optional, harmless)
config/.env.example   (template only — never a real .env)
```

**Exclude** (secrets, state, junk):
```
.env  .env.*  (except .env.example)
.venv/  __pycache__/  *.pyc
.git/  .github/
data/*.db  data/*.db-shm  data/*.db-wal
logs/  *.log
sessions/  session.json  *.bak-*
deploy/  Dockerfile  .dockerignore  DEPLOY.md
```

**Empty dirs**: include empty `data/`, `sessions/`, `logs/` if your zipper
allows (belt-and-suspenders). Not required — `run.py` creates `logs/`,
`Database.connect()` creates the `data/` parent, and
`auth/ssid_extractor._save_json` creates `sessions/` on first write.

## 2. Tranger dashboard settings

- **Runtime**: Python 3.12 (fallback 3.11).
- **Build**: `pip install -r requirements.txt` (their default).
  `pyquotex` installs from a git URL — the builder needs `git`; if the
  build fails on that line, tell me the exact error.
- **Start command**: `python run.py --mock` (explicit mock for first run).
- **Env vars** (paste into their env screen):

| Key | Value | Why |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | new rotated token | delivery |
| `TELEGRAM_ALLOWED_USERS` | `5482986556` | your id |
| `QUOTEX_EMAIL` | _(leave blank)_ | blank email forces mock (`run.py`) |
| `MOCK_SIGNAL_INTERVAL` | `10` | proven: 5 signals in ~2s of boot |
| `NEWS_FILTER_ENABLED` | `false` | matches verified local run |
| `MIN_CONFIDENCE` | `50` | verified threshold |
| `MIN_PAYOUT` | `80` | verified filter |
| `MAX_SIGNALS_PER_DAY` | `15` | verified cap |
| `BLOCKED_HOURS` | `1,11,17,20` | session filter (UTC) |
| `LOG_LEVEL` | `INFO` | log streaming |
| `QUOTEX_DEMO` | `true` | demo feed later |

Notes:
- The `playwright` **package** installs as a wheel; mock mode never
  launches Chromium, so no browser download is needed on Tranger.
- Keep `DB_PATH`/`LOG_FILE`/`SESSIONS_DIR` at their relative defaults
  (`data/`, `logs/`, `sessions/`) unless Tranger gives you a writable
  absolute path.

## 3. Verify on Tranger (mock-first)

1. Upload zip → set env → start → watch live logs.
2. Expect: `Running in MOCK mode`, seeded candles, then
   `Signal generated: EURUSD_otc CALL (57%)` (+ GBPUSD, USDJPY CALLs,
   XAUUSD/AAPL PUTs) and Telegram `sendMessage 200`.
3. Telegram → your bot → `/start`, then `/status` (mock + connected),
   `/stats` after first graded trades.
4. **Persistence check** (required — you asked for surviving history):
   note the signal count → press Tranger's **Restart** (not re-upload) →
   confirm `/stats`/signals are still there.
   - Survives restart, wiped only on re-upload → OK for validation;
     avoid needless re-uploads.
   - Wiped on restart too → report back; escalation is an external free
     DB (Turso libSQL / Neon Postgres) + a `repository.py` backend swap.

## 4. Go-live sequence (after mock is green)

1. Keep `QUOTEX_DEMO=true` 1–2 weeks on the demo feed; confirm candles,
   grading (`PENDING` → `WIN`/`LOSS`), and one full SSID cycle (~20h).
2. SSID on Tranger: set `QUOTEX_EMAIL`/`QUOTEX_PASSWORD` (+ optional
   `QUOTEX_SSID`) in env; if headless Chromium is blocked on their box,
   use the local fallback — run `python run.py --login` on your PC, then
   re-upload a zip containing the fresh `sessions/session.json`
   (one-time exception to the exclusion list).
3. Flip `QUOTEX_DEMO=false` in env → restart → re-run the §3 checklist.
   Only the account/data feed changed.

## 5. Troubleshooting

| Symptom | Likely cause → fix |
|---|---|
| Build fails on `pyquotex @ git+https` | builder lacks `git` → paste exact log; fallback is vendoring the package |
| `no such file or directory: 'data/...'` | outdated code → re-zip after the `makedirs` fix (already in repo) |
| No signals for hours | normal — confluence needs 4 aligned strategies (~1 per 200–300 candles/asset in mock; live varies) |
| Signals logged but no Telegram card | category/duration filter (`/categories`, `/duration`), `MAX_SIGNALS_PER_DAY`, or 5-min per-asset cooldown |
| OOM / killed process | free-tier RAM too small → report the limit; next step is slimming `requirements.txt` (drop pandas-ta/playwright) |
