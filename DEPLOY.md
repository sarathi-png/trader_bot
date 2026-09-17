# DEPLOY.md — Oracle Cloud Always Free (no-sleep, $0) deployment

Target: run the bot 24/7 on an **Oracle Cloud Always Free** VM that never
sleeps, then roll out **demo → live** market data.

Why Oracle and not Render/Railway/Replit/Heroku: every other free tier either
sleeps after inactivity, kills idle processes, or is a time-limited trial.
Oracle Always Free (and GCP e2-micro) are the only free-forever always-on VMs.
Oracle wins on specs: **2 OCPU / 12 GB RAM** (cut from 4/24 in June 2026 —
do not provision above 2/12), 200 GB disk, 10 TB/mo egress.

> The bot is **read-only**: it ingests candles and sends Telegram signals for
> **manual** trade execution (`core/connection.py` has no order API). "Going
> live" changes the data feed, it does not hand your account to a machine.

---

## 0. Before you start (on your own machine)

1. **Rotate secrets** — the Telegram token and Quotex password were exposed
   in earlier logs (see README § Security Note):
   - Telegram: @BotFather → `/revoke` → new `TELEGRAM_BOT_TOKEN`.
   - Quotex: change password, sign out all sessions.
2. Fill `.env` from `config/.env.example`. For the first rollout keep
   `QUOTEX_DEMO=true` (demo first, live later — §8).

---

## 1. Create the Oracle Cloud account

1. Sign up at cloud.oracle.com → **Always Free** (not the 30-day trial credits
   path). A card is required for identity verification; it is not charged for
   Always Free resources.
2. **Home region is locked at signup** — pick one with decent A1 capacity
   (EU/US regions are usually better stocked than APAC hubs). You cannot move
   it later.
3. After signup: Billing → Cost Management → **Budgets** → create a $0 budget
   alert on your email. This is your safety net against any config drift above
   the free allowance.

## 2. Create the VM

Console → Compute → Instances → Create instance:

| Setting | Value |
|---|---|
| Image | Ubuntu 22.04 or 24.04 (Minimal is fine) |
| Shape | `VM.Standard.A1.Flex` (Ampere ARM) — **1 OCPU / 6 GB** to start |
| Boot volume | 50 GB (default; stays inside the 200 GB free pool) |
| Networking | New VCN + public subnet, **assign a public IPv4** |
| SSH | Upload your public key (`ssh-keygen -t ed25519`), save the private key |

**`Out of host capacity`?** This is the known wall, not a billing problem:
- Retry off-peak (capacity frees in bursts), try another availability domain
  in the same region, or launch **1 OCPU / 6 GB** first (smaller contiguous
  block succeeds more often) and resize up later.
- Fallback: `VM.Standard.E2.1.Micro` (AMD, 1 GB RAM) — usable for this bot
  *with the 4 GB swapfile the setup script creates*; Playwright is the only
  tight part on 1 GB, and §6 gives you a local-refresh alternative.

**Idle reclaim (read this once):** Oracle may reclaim instances whose 7-day
p95 CPU, network *and* memory are all < 20%. This bot polls 15 WebSocket
assets every second plus Telegram + hourly cleanup, so a *running* bot stays
comfortably above the line. The rule only bites forgotten, truly-idle boxes.

## 3. Networking — SSH only

The bot is **outbound-only** (Quotex WebSocket out, Telegram API out). No
inbound ports are needed except SSH for administration:

- VCN Security List → Ingress → allow `0.0.0.0/0 : 22` (or your IP only).
- Nothing else. No tunnel, no reverse proxy, no domain required.

## 4. Copy code + secrets to the VM

```bash
VM=ubuntu@<VM-PUBLIC-IP>
DIR=/opt/quotex-signal-bot

ssh $VM "sudo mkdir -p $DIR && sudo chown ubuntu:ubuntu $DIR"

# Code (no venv, no state, no secrets — the script rebuilds the rest):
rsync -avz --exclude .venv --exclude __pycache__ \
  --exclude data --exclude logs --exclude sessions \
  --exclude .env --exclude "*.db*" \
  ./ $VM:$DIR/

# Secrets (create from config/.env.example on first deploy):
scp config/.env.example $VM:$DIR/.env   # then edit on the VM
ssh $VM "chmod 600 $DIR/.env && nano $DIR/.env"
```

Recommended server-side `.env` overrides (absolute paths, UTC box):

```bash
DB_PATH=/opt/quotex-signal-bot/data/signals.db
LOG_FILE=/opt/quotex-signal-bot/logs/bot.log
SESSIONS_DIR=/opt/quotex-signal-bot/sessions
QUOTEX_HEADLESS=true        # headless browser for SSID refresh (§6, option B)
QUOTEX_DEMO=true            # keep demo until §8 sign-off
```

## 5. Bootstrap the VM (one command)

```bash
ssh $VM "cd $DIR && sudo bash deploy/setup-oracle.sh $DIR ubuntu"
```

The script is idempotent — re-run it after every code update. It:
1. Installs Python/venv/git/sqlite3/build tools.
2. Creates a 4 GB swapfile if none exists.
3. Builds `.venv`, installs `requirements.txt`.
4. Installs Playwright Chromium to shared `/ms-playwright` (`--with-deps`).
5. Creates `data/ sessions/ logs/`, locks `.env` to `chmod 600`.
6. Installs + enables `quotex-bot.service`, starts it when `.env` exists.

```bash
sudo journalctl -u quotex-bot -f     # watch startup
sudo systemctl status quotex-bot     # state + recent lines
```

### Docker alternative

If you prefer containers (portable off Oracle), no systemd needed:

```bash
docker build -t quotex-bot .
docker run -d --name quotex-bot --restart=always --env-file .env \
  -v "$PWD/data:/app/data" -v "$PWD/sessions:/app/sessions" \
  -v "$PWD/logs:/app/logs" quotex-bot
docker logs -f quotex-bot
```

`.env` and state stay outside the image (see `.dockerignore`).

## 5b. Mock smoke test (prove the plumbing before credentials)

Before putting real Quotex credentials on the box, confirm the bot boots,
scores, and delivers Telegram cards with simulated data. `run.py` selects
mock mode automatically whenever no real email is configured — an untouched
copy of `config/.env.example` (`QUOTEX_EMAIL=your_email@example.com`) is
already mock:

1. Speed the smoke test up in `.env` (match the verified local run):
   ```bash
   MOCK_SIGNAL_INTERVAL=10
   NEWS_FILTER_ENABLED=false
   ```
   `sudo systemctl restart quotex-bot`
2. Expect the proven signature within seconds of boot:
   - `sudo journalctl -u quotex-bot -f` → `Running in MOCK mode with
     simulated data`, then `Signal generated: EURUSD_otc CALL (57%)` etc.
   - Telegram → your bot → `/status` → `mode: mock`, `connected: True`.
   - Signal cards arrive (EURUSD/GBPUSD/USDJPY CALL, XAUUSD/AAPL PUT).
   - Each new row is `PENDING` in `data/signals.db`; `/stats` populates.
3. Once green: restore `.env` (`MOCK_SIGNAL_INTERVAL=60`,
   `NEWS_FILTER_ENABLED=true` if desired), fill in the real `QUOTEX_EMAIL` /
   `QUOTEX_PASSWORD`, restart, and continue to §6 (SSID) → §7 (demo verify).

If the smoke test fails here, the problem is the box (venv, deps, `.env`) —
not Quotex. Fix it before burning an SSID cycle.

## 6. SSID strategy (the one cloud gotcha)

The SSID (Quotex session token) cached in `sessions/session.json` expires
after **~20 h** and auto-refreshes via Playwright → cloudscraper. The refresh
drives a real Chromium at `qxbroker.com` (Cloudflare-protected), and a
**datacenter IP can be blocked**. Pick one:

**Option A — refresh locally, sync to VM (most reliable, recommended).**
On your Windows box, run headless login on a schedule and push the token:

```powershell
# Manual refresh any time:
$env:QUOTEX_HEADLESS="true"; .venv\Scripts\python.exe run.py --login
scp sessions/session.json ubuntu@<VM-IP>:/opt/quotex-signal-bot/sessions/session.json
ssh ubuntu@<VM-IP> "sudo systemctl restart quotex-bot"
```

Automate with Task Scheduler (every 12 h): action
`powershell.exe -File C:\path\to\refresh-and-sync.ps1` where the script runs
the three lines above. The running bot picks the fresh SSID up on restart
(and on its own refresh/connect cycles).

**Option B — headless Playwright on the VM.** Already configured
(`QUOTEX_HEADLESS=true`, shared `/ms-playwright` store). Try it first — if
Cloudflare lets the login through, there is nothing else to do. If logins
start failing with blocks/captchas, fall back to Option A.

Verify the session any time: `sqlite3` isn't needed — the log line
`Connecting with SSID (bypassing HTTP login)...` followed by
`Connected to Quotex successfully` (or the watchdog retrying every 60 s)
tells you the state.

## 7. Verify the deployment (demo data)

1. Telegram → your bot → `/start`, then **`/status`** — expect
   `mode: live` (pyquotex path; "live" here means the real feed driver),
   `connected: True`, `collection_started: True`.
   (`QUOTEX_DEMO=true` still uses your **demo** account — same driver,
   demo data/payouts.)
2. `sudo journalctl -u quotex-bot -f` — expect `Discovered N assets`,
   `Loaded 300 historical candles`, then `Live candle …` lines each minute.
3. Wait for signals → cards arrive → each new signal row is `PENDING` in
   `data/signals.db`, grading to `WIN`/`LOSS` at `entry + duration`.
4. `/stats` populates after the first graded trades.
5. Add the stale-feed guard (restarts the service if logs go quiet >10 min):
   ```bash
   (crontab -l 2>/dev/null; echo "*/5 * * * * /opt/quotex-signal-bot/deploy/healthcheck.sh >> /opt/quotex-signal-bot/logs/healthcheck.log 2>&1") | crontab -
   ```

Troubleshooting quick-map:

| Symptom | Likely cause → fix |
|---|---|
| `Initial Quotex connection failed; watchdog will retry` forever | Bad/expired SSID or blocked login → `--login` (Option A/B), check `sessions/session.json` freshness |
| `Stale candle feed … no live tick` | WebSocket dropped → watchdog + healthcheck recover; persistent = IP/region block |
| `Signal generated` but no Telegram card | Category/duration filter (`/categories`, `/duration` — delivery filters per user) or `MAX_SIGNALS_PER_DAY` / 5-min per-asset cooldown |
| No signals for hours | Normal — confluence needs 4 aligned strategies (verified cadence ≈ 1 per 200–300 candles/asset in mock; live varies by market) |
| OOM on 1 GB Micro shape | Swap missing → re-run setup script §5 step 2; avoid parallel log tails |

## 8. Rollout: demo → live (your chosen sequence)

- [ ] **Phase 1 — demo (1–2 weeks).** `QUOTEX_DEMO=true` on the VM.
      Confirm: real assets/payouts, steady candle ingest, signals grade
      WIN/LOSS, `/stats` plausible, noRepeated watchdog failures, SSID
      refresh surviving at least one 20 h cycle.
- [ ] **Phase 2 — live.** Set `QUOTEX_DEMO=false` in `.env`,
      `sudo systemctl restart quotex-bot`, delete the demo `session.json`
      first so a fresh live SSID is extracted
      (`rm sessions/session.json`, then it re-authenticates on boot).
      Re-run the full §7 checklist — the *only* thing that changed is the
      account/data feed.
- [ ] **Tune for live:** `MIN_PAYOUT` (default 80), `BLOCKED_HOURS`
      (UTC rollover hours `1,11,17,20`), `MAX_SIGNALS_PER_DAY` (default 15),
      `/categories` per user.

## 9. Cost safety + ops

- Keep the **$0 budget alert** (§1). Never provision A1 above **2 OCPU /
  12 GB** on a free tenancy.
- **Update:** rsync code (same excludes as §4) → `sudo bash
  deploy/setup-oracle.sh` → `sudo systemctl restart quotex-bot`.
- **Logs:** `logs/bot.log` (app) + `journalctl -u quotex-bot` (service).
- **Backup the DB** before risky ops:
  `cp data/signals.db data/signals.db.bak-$(date +%Y%m%d)` (8-day candle
  retention runs automatically via `DB_RETENTION_DAYS`).
- **Rollback:** previous code + `sudo systemctl restart quotex-bot`; DB
  schema is migration-based (`database/`), downgrades keep old rows readable.

## Appendix — known verification limits

Built and checked on Windows: `py_compile` clean, `tests/test_fixes.py` and
`tests/test_basic.py` pass, `bash -n` clean on both scripts, Dockerfile and
systemd unit review-checked. No Docker daemon exists on this box, so
`docker build` and `systemctl` behavior must be confirmed on the VM via the
§7 checklist — that confirmation is part of this runbook, not an afterthought.
