"""Interactive Telegram Bot Runner with Dynamic Inline Menus and Complete Controls.
Allows full remote management:
- Status overview & metrics
- Run any task on-demand
- Enable/disable tasks
- Toggle global automation switch
- View latest logs and screenshots
- Backup & download system state
- AI Assistant chat directly in Telegram
"""

from __future__ import annotations
import json, os, threading, time, requests
from pathlib import Path
from datetime import datetime, timezone

from app import config

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"

def get_env_map() -> dict[str, str]:
    res = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                res[k.strip()] = v.strip().strip('"')
    for k, v in os.environ.items():
        if k not in res:
            res[k] = v
    return res

def set_env_val(key: str, val: str):
    curr = get_env_map()
    curr[key] = val
    lines = [f"{k}={v}" for k, v in curr.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = val

def call_tg(method: str, data: dict = None, files: dict = None) -> dict:
    env = get_env_map()
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {}
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        if files:
            r = requests.post(url, data=data, files=files, timeout=30)
        else:
            r = requests.post(url, json=data, timeout=20)
        return r.json()
    except Exception as exc:
        print(f"[Telegram Bot Error] {exc}")
        return {}

def send_menu(chat_id: int | str, text: str, buttons: list[list[dict]]):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": buttons}
    }
    return call_tg("sendMessage", payload)

def edit_menu(chat_id: int | str, message_id: int, text: str, buttons: list[list[dict]]):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": buttons}
    }
    return call_tg("editMessageText", payload)

def main_menu_markup() -> list[list[dict]]:
    env = get_env_map()
    auto_status = env.get("AUTOMATION_ENABLED", "false").lower() == "true"
    auto_btn_text = "[AUTOMATION: ON]" if auto_status else "[AUTOMATION: OFF]"
    
    return [
        [
            {"text": "DASHBOARD STATUS", "callback_data": "menu_status"},
            {"text": "TASK LIST", "callback_data": "menu_tasks"}
        ],
        [
            {"text": auto_btn_text, "callback_data": "toggle_auto"},
            {"text": "RUN ALL ACTIVE", "callback_data": "run_all"}
        ],
        [
            {"text": "LATEST SCREENSHOT", "callback_data": "view_screenshot"},
            {"text": "SYSTEM LOGS", "callback_data": "view_logs"}
        ],
        [
            {"text": "BACKUP SYSTEM", "callback_data": "do_backup"},
            {"text": "AI ASSISTANT", "callback_data": "ai_help"}
        ],
        [
            {"text": "REFRESH MENU", "callback_data": "menu_main"}
        ]
    ]

def get_status_text() -> str:
    from app.worker import load_tasks, STATE_FILE
    env = get_env_map()
    tasks = load_tasks()
    active_cnt = sum(1 for t in tasks if t.get("enabled"))
    
    last_run = {}
    if STATE_FILE.exists():
        try:
            last_run = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    status_str = last_run.get("status", "NO_RUN").upper()
    return (
        "<b>ORBIT CONTROL CENTER - TELEGRAM CONSOLE</b>\n"
        "------------------------------------\n"
        f"<b>Global Automation:</b> <code>{'ENABLED' if env.get('AUTOMATION_ENABLED', 'false').lower() == 'true' else 'DISABLED'}</code>\n"
        f"<b>Timezone:</b> <code>{env.get('SCHEDULE_TIMEZONE', 'Asia/Dhaka')}</code>\n"
        f"<b>Configured Tasks:</b> <code>{len(tasks)} ({active_cnt} active)</code>\n"
        f"<b>Last Task Run:</b> <code>{last_run.get('task_name', 'N/A')}</code>\n"
        f"<b>Last Status:</b> <code>[{status_str}]</code>\n"
        f"<b>Last Finished:</b> <code>{last_run.get('finished_at', 'Never')}</code>\n"
        f"<b>AI Provider:</b> <code>{env.get('ACTIVE_AI_PROVIDER', 'openai')}</code>\n"
        "------------------------------------\n"
        "<i>Select an option below to control the server:</i>"
    )

def handle_callback(cb: dict):
    from app.worker import load_tasks, save_tasks, run_task, append_history
    cq_id = cb.get("id")
    call_tg("answerCallbackQuery", {"callback_query_id": cq_id})

    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    msg_id = msg.get("message_id")
    data = cb.get("data", "")

    if data == "menu_main":
        edit_menu(chat_id, msg_id, get_status_text(), main_menu_markup())

    elif data == "menu_status":
        edit_menu(chat_id, msg_id, get_status_text(), main_menu_markup())

    elif data == "toggle_auto":
        env = get_env_map()
        new_val = "false" if env.get("AUTOMATION_ENABLED", "false").lower() == "true" else "true"
        set_env_val("AUTOMATION_ENABLED", new_val)
        edit_menu(chat_id, msg_id, f"Automation switch set to: <b>{new_val.upper()}</b>\n\n" + get_status_text(), main_menu_markup())

    elif data == "menu_tasks":
        tasks = load_tasks()
        buttons = []
        for t in tasks:
            status_txt = "ON" if t.get("enabled") else "OFF"
            buttons.append([
                {"text": f"[{status_txt}] {t.get('name')}", "callback_data": f"view_task:{t['id']}"},
                {"text": "RUN", "callback_data": f"run_task:{t['id']}"}
            ])
        buttons.append([{"text": "<< BACK TO MAIN", "callback_data": "menu_main"}])
        edit_menu(chat_id, msg_id, "<b>SELECT TASK TO MANAGE OR RUN:</b>", buttons)

    elif data.startswith("view_task:"):
        tid = data.split(":", 1)[1]
        tasks = load_tasks()
        t = next((x for x in tasks if x["id"] == tid), None)
        if not t:
            edit_menu(chat_id, msg_id, "Task not found.", [[{"text": "<< BACK", "callback_data": "menu_tasks"}]])
            return
        
        info = (
            f"<b>TASK DETAILS:</b>\n"
            f"<b>Name:</b> {t.get('name')}\n"
            f"<b>ID:</b> <code>{t.get('id')}</code>\n"
            f"<b>Kind:</b> <code>{t.get('kind')}</code>\n"
            f"<b>Schedule Time:</b> <code>{t.get('time')} ({t.get('timezone')})</code>\n"
            f"<b>Target URL:</b> <code>{t.get('url')}</code>\n"
            f"<b>Status:</b> <code>{'ENABLED' if t.get('enabled') else 'DISABLED'}</code>\n"
        )
        toggle_txt = "DISABLE TASK" if t.get("enabled") else "ENABLE TASK"
        btns = [
            [{"text": toggle_txt, "callback_data": f"toggle_task:{t['id']}"}, {"text": "EXECUTE NOW", "callback_data": f"run_task:{t['id']}"}],
            [{"text": "<< TASK LIST", "callback_data": "menu_tasks"}]
        ]
        edit_menu(chat_id, msg_id, info, btns)

    elif data.startswith("toggle_task:"):
        tid = data.split(":", 1)[1]
        tasks = load_tasks()
        for t in tasks:
            if t["id"] == tid:
                t["enabled"] = not t.get("enabled", False)
                break
        save_tasks(tasks)
        handle_callback({**cb, "data": f"view_task:{tid}"})

    elif data.startswith("run_task:"):
        tid = data.split(":", 1)[1]
        call_tg("sendMessage", {"chat_id": chat_id, "text": f"<b>Task [{tid}] started in background.</b> You will receive execution card and screenshot upon completion.", "parse_mode": "HTML"})
        threading.Thread(target=run_task, args=(tid,), daemon=True).start()

    elif data == "run_all":
        from app.worker import run_enabled_tasks
        call_tg("sendMessage", {"chat_id": chat_id, "text": "<b>Running all enabled tasks in background...</b>", "parse_mode": "HTML"})
        threading.Thread(target=run_enabled_tasks, daemon=True).start()

    elif data == "view_screenshot":
        shot_dir = ROOT / "screenshots"
        files = sorted(shot_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            latest = files[0]
            with open(latest, "rb") as f:
                call_tg("sendPhoto", {"chat_id": chat_id, "caption": f"<b>Latest Screenshot:</b> <code>{latest.name}</code>", "parse_mode": "HTML"}, files={"photo": f})
        else:
            call_tg("sendMessage", {"chat_id": chat_id, "text": "No screenshots found yet."})

    elif data == "view_logs":
        from app.worker import HISTORY_FILE
        if HISTORY_FILE.exists():
            try:
                hist = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))[:5]
                lines = ["<b>RECENT TASK EXECUTION LOGS:</b>\n------------------------------------"]
                for h in hist:
                    status_badge = "[SUCCESS]" if h.get("status") in ("success", "already_done") else "[FAILED]"
                    lines.append(f"{status_badge} <b>{h.get('task_name')}</b>")
                    lines.append(f"Time: <code>{h.get('finished_at', 'N/A')}</code>")
                    lines.append(f"Result: <code>{h.get('message') or h.get('error', 'Completed')}</code>\n")
                lines.append("------------------------------------")
                call_tg("sendMessage", {"chat_id": chat_id, "text": "\n".join(lines), "parse_mode": "HTML"})
            except Exception as exc:
                call_tg("sendMessage", {"chat_id": chat_id, "text": f"Error reading logs: {exc}"})
        else:
            call_tg("sendMessage", {"chat_id": chat_id, "text": "No history logs recorded."})

    elif data == "do_backup":
        from app.main import make_backup_zip
        zip_path = make_backup_zip()
        if zip_path.exists():
            with open(zip_path, "rb") as f:
                call_tg("sendDocument", {"chat_id": chat_id, "caption": f"<b>System Backup Package</b>\nGenerated at: <code>{datetime.now().isoformat()}</code>", "parse_mode": "HTML"}, files={"document": f})
        else:
            call_tg("sendMessage", {"chat_id": chat_id, "text": "Backup failed to generate."})

    elif data == "ai_help":
        msg_text = (
            "<b>ORBIT AI ASSISTANT IN TELEGRAM:</b>\n\n"
            "Simply send any plain text message to this bot, and the configured AI engine will answer with expert browser automation guidance, selector fixes, or schedule recommendations."
        )
        call_tg("sendMessage", {"chat_id": chat_id, "text": msg_text, "parse_mode": "HTML"})

def handle_text_message(msg: dict):
    from app.main import ai_request
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    if text.startswith("/start") or text.startswith("/menu"):
        send_menu(chat_id, get_status_text(), main_menu_markup())
        return

    if text.startswith("/status"):
        call_tg("sendMessage", {"chat_id": chat_id, "text": get_status_text(), "parse_mode": "HTML"})
        return

    if text.startswith("/backup"):
        from app.main import make_backup_zip
        zip_path = make_backup_zip()
        with open(zip_path, "rb") as f:
            call_tg("sendDocument", {"chat_id": chat_id, "caption": "Requested System Backup", "parse_mode": "HTML"}, files={"document": f})
        return

    # If it's a general question, route through AI Assistant
    env = get_env_map()
    provider = env.get("ACTIVE_AI_PROVIDER", "openai")
    model = env.get("ACTIVE_AI_MODEL", "")

    call_tg("sendChatAction", {"chat_id": chat_id, "action": "typing"})
    try:
        reply = ai_request(provider, model, text, use_system=True)
        call_tg("sendMessage", {"chat_id": chat_id, "text": reply[:4000], "parse_mode": "Markdown"})
    except Exception as exc:
        call_tg("sendMessage", {"chat_id": chat_id, "text": f"<b>AI Query Error:</b> {exc}", "parse_mode": "HTML"})

_bot_thread: threading.Thread | None = None
_bot_running = False

def poll_telegram_loop():
    global _bot_running
    offset = 0
    print("[Telegram Bot] Poller started.")
    while _bot_running:
        env = get_env_map()
        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            time.sleep(5)
            continue
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": offset, "timeout": 20},
                timeout=30
            )
            if r.status_code == 200:
                res = r.json()
                for upd in res.get("result", []):
                    offset = upd["update_id"] + 1
                    if "callback_query" in upd:
                        handle_callback(upd["callback_query"])
                    elif "message" in upd:
                        handle_text_message(upd["message"])
            time.sleep(0.5)
        except Exception:
            time.sleep(3)

def start_telegram_bot():
    global _bot_thread, _bot_running
    if _bot_running:
        return
    _bot_running = True
    _bot_thread = threading.Thread(target=poll_telegram_loop, daemon=True)
    _bot_thread.start()

def stop_telegram_bot():
    global _bot_running
    _bot_running = False
