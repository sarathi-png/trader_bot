import asyncio
import json
import logging
import os
import re
import time
import base64
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

SESSION_DIR = Path(__file__).resolve().parent.parent / "sessions"
SESSION_FILE = SESSION_DIR / "session.json"
CONFIG_FILE = SESSION_DIR / "config.json"

QUOTEX_HOST = "qxbroker.com"
SIGN_IN_URL = f"https://{QUOTEX_HOST}/en/sign-in/"
TRADE_URL = f"https://{QUOTEX_HOST}/en/trade"
DEMO_TRADE_URL = f"https://{QUOTEX_HOST}/en/demo-trade"


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_session(ssid: str, is_demo: bool = True, cookies: str = "", user_agent: str = "") -> None:
    data = {
        "ssid": ssid,
        "is_demo": is_demo,
        "cookies": cookies,
        "user_agent": user_agent,
        "timestamp": time.time(),
    }
    _save_json(SESSION_FILE, data)
    logger.info(f"Session saved to {SESSION_FILE}")


def load_session() -> Optional[Dict[str, Any]]:
    data = _load_json(SESSION_FILE)
    ssid = data.get("ssid")
    if ssid and len(ssid) >= 8:
        return data
    return None


def delete_session() -> None:
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()
        logger.info("Session file deleted")


def is_session_expired(max_age_hours: int = 24) -> bool:
    data = _load_json(SESSION_FILE)
    ts = data.get("timestamp", 0)
    if ts == 0:
        return True
    age_hours = (time.time() - ts) / 3600
    return age_hours > max_age_hours


def _extract_ssid_from_socketio(payload: str) -> Optional[str]:
    try:
        idx = payload.find("[")
        if idx == -1:
            return None
        arr_text = payload[idx:]
        arr = json.loads(arr_text)
        if isinstance(arr, list) and len(arr) >= 2:
            event = arr[0]
            data = arr[1]
            if isinstance(event, str) and isinstance(data, dict):
                if event.lower() in ("authorization", "authorize", "auth", "authenticated"):
                    ssid = data.get("session")
                    if isinstance(ssid, str) and len(ssid) >= 8:
                        return ssid
                for k, v in data.items():
                    if isinstance(k, str) and "session" in k.lower() and isinstance(v, str) and len(v) >= 8:
                        return v
    except Exception:
        pass
    return None


def _extract_ssid_from_payload(payload: str) -> Optional[str]:
    ssid = _extract_ssid_from_socketio(payload)
    if ssid:
        return ssid

    try:
        obj = json.loads(payload)
        if isinstance(obj, dict):
            for key in ("session", "ssid", "sessionId", "session_id"):
                val = obj.get(key)
                if isinstance(val, str) and len(val) >= 8:
                    return val
            for key in ("message", "data", "payload"):
                sub = obj.get(key)
                if isinstance(sub, dict):
                    for k2 in ("session", "ssid", "sessionId", "session_id"):
                        val = sub.get(k2)
                        if isinstance(val, str) and len(val) >= 8:
                            return val
    except Exception:
        pass

    try:
        s = payload.strip()
        if re.fullmatch(r"[A-Za-z0-9_\-+/=]+", s) and len(s) >= 16:
            missing = (-len(s)) % 4
            if missing:
                s += "=" * missing
            decoded = base64.b64decode(s)
            as_text = decoded.decode("utf-8", errors="ignore")
            m = re.search(r'"session"\s*:\s*"([^"]{8,})"', as_text)
            if m:
                return m.group(1)
            try:
                obj2 = json.loads(as_text)
                if isinstance(obj2, dict):
                    for key in ("session", "ssid", "sessionId", "session_id"):
                        val = obj2.get(key)
                        if isinstance(val, str) and len(val) >= 8:
                            return val
            except Exception:
                pass
    except Exception:
        pass

    m = re.search(r'"session"\s*:\s*"([^"]{8,})"', payload)
    if m:
        return m.group(1)
    return None


async def _try_cloudscraper_login(email: str, password: str) -> Optional[str]:
    try:
        import cloudscraper
        from bs4 import BeautifulSoup
    except ImportError:
        logger.debug("cloudscraper not installed, skipping HTTP login path")
        return None

    logger.info("Trying Cloudscraper (fast HTTP login)...")
    session = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )

    try:
        resp = session.get(SIGN_IN_URL, timeout=15)
        if resp.status_code != 200:
            logger.warning(f"Cloudscraper: sign-in page returned {resp.status_code}")
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        token_input = soup.find("input", {"name": "_token"})
        csrf_token = token_input.get("value", "") if token_input else ""

        cookies_str = "; ".join(f"{k}={v}" for k, v in session.cookies.items())

        data = {
            "_token": csrf_token,
            "email": email,
            "password": password,
            "remember": 1,
        }
        headers = {
            "Referer": SIGN_IN_URL,
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookies_str,
        }

        resp2 = session.post(f"{SIGN_IN_URL}", data=data, headers=headers, timeout=15, allow_redirects=True)

        if "trade" not in resp2.url:
            logger.warning(f"Cloudscraper: login redirect did not reach trade page: {resp2.url}")
            return None

        soup2 = BeautifulSoup(resp2.text, "html.parser")
        scripts = soup2.find_all("script", {"type": "text/javascript"})
        for script in scripts:
            text = script.get_text()
            match = re.search(r"window\.settings\s*=\s*({.*?})\s*;?", text, re.DOTALL)
            if match:
                try:
                    settings = json.loads(match.group(1))
                    token = settings.get("token")
                    if token and isinstance(token, str) and len(token) >= 8:
                        logger.info("Cloudscraper: SSID extracted from window.settings")
                        return token
                except json.JSONDecodeError:
                    pass

        for cookie in session.cookies:
            if cookie.name in ("session", "ssid", "token") and len(cookie.value) >= 8:
                logger.info(f"Cloudscraper: SSID extracted from cookie '{cookie.name}'")
                return cookie.value

        logger.warning("Cloudscraper: could not extract SSID from response")
        return None

    except Exception as e:
        logger.warning(f"Cloudscraper login failed: {e}")
        return None


async def _playwright_login(email: str, password: str, headless: bool = False) -> Optional[str]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        return None

    logger.info(f"Launching Playwright browser (headless={headless})...")
    ssid_captured: Optional[str] = None
    ssid_event = asyncio.Event()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--ignore-certificate-errors",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            permissions=["notifications"],
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        try:
            await context.grant_permissions(["notifications"], origin=f"https://{QUOTEX_HOST}")
        except Exception:
            pass

        page = await context.new_page()

        async def on_response(response):
            nonlocal ssid_captured
            if ssid_captured:
                return
            try:
                ct = response.headers.get("content-type", "")
                if "application/json" in ct:
                    text = await response.text()
                    m = re.search(r'"session"\\s*:\\s*"([^"]{8,})"', text)
                    if m:
                        ssid_captured = m.group(1)
                        logger.info(f"SSID captured via HTTP response")
                        ssid_event.set()
            except Exception:
                pass

        page.on("response", on_response)

        def on_websocket(ws):
            nonlocal ssid_captured
            logger.info(f"WebSocket created: {ws.url}")

            async def _handle_payload(payload: str):
                nonlocal ssid_captured
                if ssid_captured:
                    return
                ssid = _extract_ssid_from_payload(payload)
                if ssid:
                    ssid_captured = ssid
                    logger.info("SSID captured via WebSocket frame")
                    ssid_event.set()

            def _frame_received(payload: str):
                asyncio.create_task(_handle_payload(payload))

            ws.on("framereceived", _frame_received)
            ws.on("framesent", _frame_received)

        page.on("websocket", on_websocket)

        logger.info(f"Navigating to {SIGN_IN_URL}")
        await page.goto(SIGN_IN_URL, wait_until="domcontentloaded", timeout=60000)

        await _dismiss_banners(page)
        await _fill_login_form(page, email, password)

        try:
            await asyncio.wait_for(ssid_event.wait(), timeout=45)
            logger.info("SSID captured successfully from network")
        except asyncio.TimeoutError:
            logger.info("SSID not captured from network, scanning client storage...")
            ssid_captured = await _scan_client_storage(page)

        await browser.close()

    return ssid_captured


async def _dismiss_banners(page) -> None:
    selectors = [
        'button:has-text("Accept all")',
        'button:has-text("Allow all")',
        'button:has-text("I Agree")',
        'button:has-text("I agree")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
        '#onetrust-accept-btn-handler',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if await loc.count():
                await loc.first.click(timeout=800)
                await page.wait_for_timeout(200)
        except Exception:
            continue
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        await page.evaluate("""() => {
            document.querySelectorAll('#portal, .modal, .overlay').forEach(p => {
                try { p.remove(); } catch(e) {}
            });
        }""")
    except Exception:
        pass


async def _fill_login_form(page, email: str, password: str) -> None:
    await page.wait_for_load_state("domcontentloaded")

    try:
        login_tab = page.locator("#tab-1")
        if not await login_tab.is_visible():
            tab_btn = page.locator('.modal-sign__tabs-block a.modal-sign__tab', has_text="Login").first
            await tab_btn.click(timeout=3000)
            await page.wait_for_timeout(300)
        await login_tab.wait_for(state="visible", timeout=8000)
    except Exception:
        try:
            await page.locator('a.header__button-log-in, a[href*="/sign-in"]').first.click(timeout=2000)
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass

    email_selectors = [
        '#tab-1 input[name="email"]',
        '#tab-1 input[type="email"]',
        'input[name="email"]',
        'input[type="email"]',
        'input[placeholder*="mail" i]',
    ]
    for sel in email_selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=4000)
            await el.fill(email, timeout=2500)
            logger.info(f"Filled email via: {sel}")
            break
        except Exception:
            continue

    pass_selectors = [
        '#tab-1 input[name="password"]',
        '#tab-1 input[type="password"]',
        'input[name="password"]',
        'input[type="password"]',
    ]
    for sel in pass_selectors:
        try:
            el = page.locator(sel).first
            await el.wait_for(state="visible", timeout=4000)
            await el.fill(password, timeout=2500)
            logger.info(f"Filled password via: {sel}")
            break
        except Exception:
            continue

    submit_selectors = [
        '#tab-1 button.modal-sign__block-button:has-text("Sign in")',
        '#tab-1 button:has-text("Sign in")',
        'button[type="submit"]',
        'button:has-text("Sign in")',
        'button:has-text("Log in")',
    ]
    for sel in submit_selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count():
                await btn.click(timeout=2500)
                logger.info(f"Clicked submit via: {sel}")
                break
        except Exception:
            continue
    else:
        try:
            await page.keyboard.press("Enter")
            logger.info("Submitted via Enter key")
        except Exception:
            pass

    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass


async def _scan_client_storage(page) -> Optional[str]:
    try:
        ssid = await page.evaluate("""() => {
            try {
                for (let i = 0; i < localStorage.length; i++) {
                    const k = localStorage.key(i);
                    const v = localStorage.getItem(k) || "";
                    if (/session|ssid/i.test(k) && typeof v === 'string' && v.length >= 8) return v;
                    const m = /"session"\\s*:\\s*"([^"]{8,})"/.exec(v);
                    if (m) return m[1];
                }
                for (const k of Object.keys(window)) {
                    if (/session|ssid/i.test(k)) {
                        const v = window[k];
                        if (v && typeof v === 'string' && v.length >= 8) return v;
                    }
                }
                const parts = (document.cookie || '').split(';');
                for (const p of parts) {
                    const [ck, cv] = p.split('=');
                    if (/session|ssid/i.test(ck || '') && (cv || '').length >= 8) return cv;
                }
            } catch (e) {}
            return null;
        }""")
        if ssid and isinstance(ssid, str):
            return ssid
    except Exception:
        pass
    return None


async def validate_ssid(ssid: str) -> bool:
    try:
        import websockets
    except ImportError:
        logger.debug("websockets not installed, cannot validate SSID")
        return True

    auth_msg = json.dumps(["authorization", {
        "session": ssid,
        "isDemo": 1,
        "tournamentId": 0,
    }])
    ws_msg = f'42{auth_msg}'

    for region in ["ws2", "ws3", "ws4"]:
        url = f"wss://{region}.{QUOTEX_HOST}/socket.io/?EIO=3&transport=websocket"
        try:
            async with websockets.connect(
                url,
                extra_headers={
                    "Origin": f"https://{QUOTEX_HOST}",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
                ping_interval=None,
                close_timeout=5,
            ) as ws:
                deadline = time.time() + 10
                while time.time() < deadline:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    if msg == "40":
                        await ws.send(ws_msg)
                    elif "s_authorization" in msg:
                        logger.info(f"SSID validated OK via {region}")
                        return True
                    elif "authorization/reject" in msg:
                        logger.warning("SSID rejected by server")
                        return False
                    elif msg == "2":
                        await ws.send("3")
        except Exception as e:
            logger.debug(f"SSID validation via {region} failed: {e}")
            continue

    logger.warning("SSID validation failed on all regions")
    return False


async def get_or_refresh_ssid(
    email: str = "",
    password: str = "",
    force_refresh: bool = False,
    headless: bool = False,
    is_demo: bool = True,
) -> Optional[str]:
    if not force_refresh:
        session = load_session()
        if session:
            ssid = session.get("ssid", "")
            if ssid and not is_session_expired(max_age_hours=20):
                logger.info("Using cached SSID from session file")
                return ssid
            elif ssid:
                logger.info("Cached SSID is expired, refreshing...")

    if not email or not password:
        logger.error("No email/password provided for SSID extraction")
        session = load_session()
        if session:
            return session.get("ssid")
        return None

    logger.info("Attempting SSID extraction...")
    ssid = await _try_cloudscraper_login(email, password)

    if not ssid:
        logger.info("Cloudscraper failed, falling back to Playwright...")
        ssid = await _playwright_login(email, password, headless=headless)

    if ssid:
        save_session(ssid, is_demo=is_demo)
        logger.info(f"SSID extraction successful: {ssid[:8]}...")
        return ssid
    else:
        logger.error("All SSID extraction methods failed")
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    async def _main():
        email = os.environ.get("QUOTEX_EMAIL", "")
        password = os.environ.get("QUOTEX_PASSWORD", "")
        if not email or not password:
            email = input("Email: ").strip()
            password = input("Password: ").strip()

        ssid = await get_or_refresh_ssid(email=email, password=password, headless=False)
        if ssid:
            print(f"\nSuccess! SSID: {ssid[:12]}...")
            print(f"Saved to: {SESSION_FILE}")
        else:
            print("\nFailed to extract SSID.")

    asyncio.run(_main())
