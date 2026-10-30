from __future__ import annotations

import json, os, re, time, traceback, glob
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
SCREENSHOT_DIR = ROOT / "screenshots"
TASKS_FILE = ROOT / "data" / "tasks.json"
STATE_FILE = LOG_DIR / "last_run.json"
HISTORY_FILE = LOG_DIR / "history.json"
for folder in (LOG_DIR, SCREENSHOT_DIR, TASKS_FILE.parent):
    folder.mkdir(exist_ok=True)


def load_local_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))

load_local_env()

DEFAULT_TASKS = [
    {
        "id": "daily-rewards",
        "name": "Claim Daily Rewards",
        "kind": "daily_rewards",
        "url": "https://vyceai.com/dashboard-v2",
        "time": "20:17",
        "timezone": "Asia/Dhaka",
        "enabled": True,
        "screenshot": True,
        "retention_hours": 12
    },
    {
        "id": "available-balance",
        "name": "Check Available Balance",
        "kind": "available_balance",
        "url": "https://vyceai.com/dashboard-v2",
        "time": "20:20",
        "timezone": "Asia/Dhaka",
        "enabled": False,
        "screenshot": True,
        "retention_hours": 12
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_tasks() -> list[dict[str, Any]]:
    if not TASKS_FILE.exists():
        TASKS_FILE.write_text(json.dumps(DEFAULT_TASKS, ensure_ascii=False, indent=2))
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_TASKS.copy()

def save_tasks(tasks: list[dict[str, Any]]) -> None:
    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")

def save_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

def append_history(result: dict[str, Any]) -> None:
    try:
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    except Exception:
        history = []
    history.insert(0, result)
    save_json(HISTORY_FILE, history[:100])
    save_json(STATE_FILE, result)

def send_telegram_card(token: str, chat_id: str, title: str, status: str, details: list[tuple[str, str]], screenshot_path: str = "") -> dict[str, str]:
    """Sends a cleanly structured, professional card with optional photo via Telegram Bot API."""
    badge = "[SUCCESS]" if status.lower() in ("success", "already_done") else "[FAILED]"
    
    caption_lines = [
        f"<b>ORBIT AUTOMATION SYSTEM</b>",
        f"<b>Task:</b> {title}",
        f"<b>Status:</b> {badge} {status.upper()}",
        f"<b>Timestamp:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "------------------------------------"
    ]
    for key, val in details:
        if val:
            caption_lines.append(f"<b>{key}:</b> <code>{str(val)[:250]}</code>")
    caption_lines.append("------------------------------------")
    caption_lines.append("<i>Managed via Orbit Assistant Dashboard</i>")
    caption = "\n".join(caption_lines)

    # Check if screenshot exists and is accessible
    actual_photo = None
    if screenshot_path:
        cand = Path(screenshot_path)
        if not cand.is_absolute():
            cand = ROOT / screenshot_path
        if cand.exists() and cand.is_file():
            actual_photo = cand

    try:
        if actual_photo:
            with open(actual_photo, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"},
                    files={"photo": f},
                    timeout=30
                )
                r.raise_for_status()
                return {"telegram": "photo_sent"}
        else:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": caption[:4096], "parse_mode": "HTML"},
                timeout=20
            )
            r.raise_for_status()
            return {"telegram": "message_sent"}
    except Exception as exc:
        return {"telegram": f"failed: {exc}"}

def send_notifications(message: str, screenshot: str = "", extra_data: dict[str, Any] | None = None) -> dict[str, str]:
    results: dict[str, str] = {}
    extra = extra_data or {}
    
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    
    if token and chat_id:
        status = extra.get("status", "info")
        task_name = extra.get("task_name", "Automation Notification")
        details = [
            ("Message", extra.get("message") or message),
            ("URL", extra.get("url", "")),
            ("Execution Time", extra.get("finished_at", "")),
        ]
        if extra.get("error"):
            details.append(("Error Details", extra.get("error")))
        if extra.get("balance_matches"):
            details.append(("Balance Found", "\n".join(extra.get("balance_matches")[:5])))

        tg_res = send_telegram_card(token, chat_id, task_name, status, details, screenshot)
        results.update(tg_res)

    webhook = os.getenv("WEBHOOK_URL", "").strip()
    if webhook:
        try:
            full = message + (f"\nScreenshot: {screenshot}" if screenshot else "")
            requests.post(webhook, json={"text": full, "content": full, "extra": extra}, timeout=15).raise_for_status()
            results["webhook"] = "sent"
        except Exception as exc:
            results["webhook"] = f"failed: {exc}"

    fcm = os.getenv("FCM_TOKEN", "").strip()
    service_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if fcm and service_json:
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request
            info = json.loads(service_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
            creds.refresh(Request())
            project_id = info.get("project_id")
            if not project_id:
                raise RuntimeError("service account JSON has no project_id")
            url = f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
            payload = {"message": {"token": fcm, "notification": {"title": extra.get("task_name", "Orbit Assistant"), "body": message[:900]}}}
            requests.post(url, headers={"Authorization": "Bearer " + creds.token, "Content-Type": "application/json"}, json=payload, timeout=20).raise_for_status()
            results["fcm"] = "sent"
        except Exception as exc:
            results["fcm"] = f"failed: {exc}"
    return results

def notify(message: str, screenshot: str = "", extra_data: dict[str, Any] | None = None) -> None:
    send_notifications(message, screenshot, extra_data)

def cleanup_screenshots(retention_hours: float | None = None) -> None:
    hours = retention_hours if retention_hours is not None else float(os.getenv("SCREENSHOT_RETENTION_HOURS", "24"))
    cutoff = time.time() - float(hours) * 3600
    for path in SCREENSHOT_DIR.glob("*.png"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass

def _find_chromium() -> str:
    """Find chromium executable - works both locally, in Docker, and Playwright default."""
    explicit = os.getenv("CHROMIUM_PATH", "").strip()
    if explicit and not any(c in explicit for c in ["*", "?"]):
        if Path(explicit).exists():
            return explicit

    pw_path = os.getenv("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")
    patterns = [
        f"{pw_path}/chromium-*/chrome-linux/chrome",
        f"{pw_path}/chromium-*/chrome-linux/chromium",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/local/bin/chromium",
    ]
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches and Path(matches[0]).exists():
            return matches[0]
    return ""

def _first_visible(page, selectors: list[str]):
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=800):
                return loc
        except Exception:
            continue
    return None

def _login(page) -> None:
    email = os.getenv("TARGET_EMAIL", "")
    password = os.getenv("TARGET_PASSWORD", "")
    if not email or not password:
        raise RuntimeError("TARGET_EMAIL or TARGET_PASSWORD not configured in Settings / .env")
    page.goto(os.getenv("LOGIN_URL", "https://vyceai.com/login"), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3000)
    email_input = _first_visible(page, ["input[type=email]", "input[name*=email i]", "input[placeholder*=email i]"])
    password_input = _first_visible(page, ["input[type=password]", "input[name*=pass i]"])
    button = _first_visible(page, ["button[type=submit]", "input[type=submit]", "button:has-text('Log in')", "button:has-text('Login')", "button:has-text('Sign in')"])
    if not email_input or not password_input or not button:
        raise RuntimeError(f"Could not locate login controls at {page.url}")
    email_input.fill(email)
    password_input.fill(password)
    button.click()
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    page.wait_for_timeout(10000)
    if "login" in page.url.lower() or "signin" in page.url.lower():
        raise RuntimeError("Login failed or requires CAPTCHA/MFA verification.")

def _resolve(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Z0-9_]+)\}", lambda m: os.getenv(m.group(1), ""), value)
    return value

def _run_custom(page, task: dict[str, Any], result: dict[str, Any]) -> None:
    steps = task.get("steps") or []
    if not steps:
        raise RuntimeError("Custom task has no steps. Add step list in the task editor.")
    extracted = {}
    for step in steps:
        action = step.get("action")
        if action == "goto":
            page.goto(_resolve(step.get("url", task.get("url"))), wait_until="domcontentloaded", timeout=60000)
        elif action == "click":
            loc = _first_visible(page, [_resolve(step.get("selector", ""))])
            if not loc:
                raise RuntimeError(f"Click target not found: {step.get('selector')}")
            loc.click()
        elif action == "click_text":
            page.get_by_text(_resolve(step.get("text", "")), exact=False).first.click()
        elif action == "fill":
            loc = page.locator(_resolve(step.get("selector", ""))).first
            loc.fill(_resolve(step.get("value", "")))
        elif action == "wait":
            page.wait_for_timeout(int(step.get("ms", 1000)))
        elif action == "extract_text":
            selector = _resolve(step.get("selector", "body"))
            extracted[step.get("name", "text")] = page.locator(selector).inner_text(timeout=15000)
        elif action == "screenshot":
            page.screenshot(path=str(SCREENSHOT_DIR / f"{task['id']}-step-{len(extracted)}.png"), full_page=True)
        else:
            raise RuntimeError(f"Unsupported action: {action}")
    result.update({"status": "success", "message": "Custom task completed successfully.", "extracted": extracted})

def run_task(task_id: str = "daily-rewards") -> dict[str, Any]:
    task = next((t for t in load_tasks() if t.get("id") == task_id), None)
    if not task:
        raise ValueError(f"Unknown task: {task_id}")
    cleanup_screenshots(task.get("retention_hours"))
    started = now_iso()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    shot = SCREENSHOT_DIR / f"{task_id}-{stamp}.png"
    result: dict[str, Any] = {
        "task_id": task_id,
        "task_name": task.get("name"),
        "started_at": started,
        "status": "failed",
        "screenshot": str(shot.relative_to(ROOT))
    }

    chromium_path = _find_chromium()

    with sync_playwright() as p:
        launch_kwargs: dict[str, Any] = {
            "headless": os.getenv("HEADLESS", "true").lower() != "false",
            "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        }
        if chromium_path:
            launch_kwargs["executable_path"] = chromium_path

        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page = context.new_page()
        try:
            _login(page)
            page.goto(task.get("url", "https://vyceai.com/dashboard-v2"), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            if task.get("kind") == "daily_rewards":
                nav = _first_visible(page, ["text=Daily Rewards", "button:has-text('Daily Rewards')", "a:has-text('Daily Rewards')"])
                if not nav:
                    raise RuntimeError("Daily Rewards navigation item not found.")
                nav.click()
                page.wait_for_timeout(7000)
                body = page.locator("body").inner_text(timeout=15000)
                claim = _first_visible(page, ["button:has-text('Claim daily')", "button:has-text('Claim Daily')", "text=Claim daily reward"])
                if claim:
                    claim.click()
                    page.wait_for_timeout(2500)
                    result.update({"status": "success", "message": "Daily reward claimed successfully.", "detail": page.locator("body").inner_text()[-1000:]})
                elif re.search(r"Next reward in|already claimed|come back", body, re.I):
                    result.update({"status": "already_done", "message": "Daily reward was already claimed today.", "detail": body[-1000:]})
                else:
                    raise RuntimeError("Daily Rewards page reached, but no claim button or claim status detected.")
            elif task.get("kind") == "available_balance":
                body = page.locator("body").inner_text(timeout=15000)
                matches = [line.strip() for line in body.splitlines() if re.search(r"balance|available", line, re.I)]
                result.update({"status": "success", "message": "Available balance retrieved.", "balance_matches": matches[:20]})
            elif task.get("kind") == "custom":
                _run_custom(page, task, result)
            else:
                raise RuntimeError(f"Unsupported task kind: {task.get('kind')}")
            
            if task.get("screenshot", True):
                page.screenshot(path=str(shot), full_page=True)
            else:
                result["screenshot"] = ""
        except Exception as exc:
            result.update({"error": str(exc), "trace": traceback.format_exc(limit=3), "url": page.url})
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:
                pass
        finally:
            result["finished_at"] = now_iso()
            append_history(result)
            # Dispatch rich formatted telegram notification with photo
            summary_msg = f"{result.get('task_name')}: {result.get('message', result.get('error', 'Execution completed'))}"
            notify(summary_msg, result.get("screenshot", ""), extra_data=result)
            context.close()
            browser.close()
    return result

def run_enabled_tasks() -> list[dict[str, Any]]:
    return [run_task(t["id"]) for t in load_tasks() if t.get("enabled")]

if __name__ == "__main__":
    run_enabled_tasks()
