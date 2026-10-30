from __future__ import annotations

import json, os, threading, uuid, shutil, zipfile
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, Form, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel
import requests

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR, SCREENSHOT_DIR, DATA_DIR, BACKUP_DIR = ROOT / "logs", ROOT / "screenshots", ROOT / "data", ROOT / "backups"
for folder in (LOG_DIR, SCREENSHOT_DIR, DATA_DIR, BACKUP_DIR):
    folder.mkdir(exist_ok=True)
ENV_FILE, TASKS_FILE = ROOT / ".env", DATA_DIR / "tasks.json"

app = FastAPI(title="Orbit Browser Assistant")

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

# Free and standard AI provider configurations
FREE_PROVIDERS = [
    {
        "id": "openrouter",
        "name": "OpenRouter (Free Tier)",
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "free": True,
        "free_models": [
            "meta-llama/llama-3.1-8b-instruct:free",
            "mistralai/mistral-7b-instruct:free",
            "google/gemma-2-9b-it:free",
            "microsoft/phi-3-mini-128k-instruct:free",
            "qwen/qwen-2-7b-instruct:free",
            "openchat/openchat-7b:free",
            "huggingfaceh4/zephyr-7b-beta:free",
            "nousresearch/nous-capybara-7b:free",
        ],
    },
    {
        "id": "groq",
        "name": "Groq (High-Speed Free)",
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "free": True,
        "free_models": [
            "llama-3.1-8b-instant",
            "llama3-8b-8192",
            "gemma2-9b-it",
            "mixtral-8x7b-32768",
        ],
    },
    {
        "id": "together",
        "name": "Together AI (Free Tier)",
        "base_url": "https://api.together.xyz/v1",
        "key_env": "TOGETHER_API_KEY",
        "free": True,
        "free_models": [
            "meta-llama/Llama-3-8b-chat-hf",
            "mistralai/Mistral-7B-Instruct-v0.1",
            "google/gemma-2b-it",
        ],
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "base_url": None,
        "key_env": "GEMINI_API_KEY",
        "free": True,
        "free_models": ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "free": False,
        "free_models": ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
    },
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "base_url": None,
        "key_env": "ANTHROPIC_API_KEY",
        "free": False,
        "free_models": ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"],
    },
    {
        "id": "custom",
        "name": "Custom OpenAI-compatible",
        "base_url": None,
        "key_env": "CUSTOM_AI_API_KEY",
        "free": False,
        "free_models": [],
    },
]

AI_SYSTEM_PROMPT = """You are Orbit AI Assistant, an expert browser automation engineer.
You help operators:
- Write and refine Playwright automation steps
- Debug target selectors, timing, and login authentication
- Configure daily reward claims, balance checks, and custom steps
- Setup Telegram bots, webhooks, and push notifications
- Recommend optimal free and high-speed AI providers

When proposing automation steps, format as valid JSON array:
[
  {"action": "goto", "url": "https://example.com"},
  {"action": "click", "selector": "button.primary"},
  {"action": "wait", "ms": 2000},
  {"action": "extract_text", "selector": ".balance-val", "name": "balance"},
  {"action": "screenshot"}
]
Actions allowed: goto, click, click_text, fill, wait, extract_text, screenshot.
Keep answers professional, clean, and without emojis."""

def load_env_file():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

load_env_file()

def env_value(key: str, default: str = "") -> str:
    return os.getenv(key, default)

def get_all_env_dict() -> dict[str, str]:
    """Returns all key-values from the .env file."""
    res = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                res[k.strip()] = v.strip().strip('"')
    return res

def update_env(values: dict[str, str]) -> None:
    current = get_all_env_dict()
    current.update({k: str(v) for k, v in values.items() if v is not None})
    lines = [f"{k}={v}" for k, v in sorted(current.items())]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except Exception:
        pass
    os.environ.update(current)

def load_tasks():
    if not TASKS_FILE.exists():
        TASKS_FILE.write_text(json.dumps(DEFAULT_TASKS, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_TASKS.copy()

def save_tasks(tasks):
    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")

def state():
    p = LOG_DIR / "last_run.json"
    if not p.exists():
        return {"status": "not_run", "message": "No task executed yet."}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "unknown"}

def history():
    p = LOG_DIR / "history.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))[:30]
    except Exception:
        return []

def make_backup_zip() -> Path:
    """Creates a full system archive including tasks, logs, and env settings."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = BACKUP_DIR / f"orbit_backup_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if ENV_FILE.exists():
            zf.write(ENV_FILE, arcname=".env")
        if TASKS_FILE.exists():
            zf.write(TASKS_FILE, arcname="data/tasks.json")
        for f in LOG_DIR.glob("*.json"):
            zf.write(f, arcname=f"logs/{f.name}")
    return zip_path

def restore_from_zip(zip_path: Path) -> dict[str, Any]:
    """Restores tasks, env settings, and logs from a backup archive."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.namelist()
        if ".env" in members:
            content = zf.read(".env").decode("utf-8")
            ENV_FILE.write_text(content, encoding="utf-8")
            load_env_file()
        if "data/tasks.json" in members:
            content = zf.read("data/tasks.json").decode("utf-8")
            TASKS_FILE.write_text(content, encoding="utf-8")
        for m in members:
            if m.startswith("logs/") and m.endswith(".json"):
                target = LOG_DIR / Path(m).name
                target.write_bytes(zf.read(m))
    return {"ok": True, "message": "System successfully restored from backup."}

@app.on_event("startup")
def startup_tasks():
    # Start telegram bot listener in background thread if configured
    from app.telegram_bot import start_telegram_bot
    start_telegram_bot()

@app.get("/", response_class=HTMLResponse)
def dashboard():
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template = Environment(loader=FileSystemLoader(str(ROOT / "templates")), autoescape=select_autoescape()).get_template("index.html")
    return HTMLResponse(template.render(
        tasks=load_tasks(),
        state=state(),
        history=history(),
        enabled=env_value("AUTOMATION_ENABLED", "false"),
        timezone=env_value("SCHEDULE_TIMEZONE", "Asia/Dhaka"),
        tg=bool(env_value("TELEGRAM_BOT_TOKEN")),
        all_env=get_all_env_dict()
    ))

class TaskPayload(BaseModel):
    name: str
    kind: str = "available_balance"
    url: str = "https://vyceai.com/dashboard-v2"
    time: str = "20:17"
    timezone: str = "Asia/Dhaka"
    enabled: bool = False
    screenshot: bool = True
    retention_hours: int = 12
    steps: list[dict] = []

class EnvUpdatePayload(BaseModel):
    env_content: str = ""
    env_dict: dict[str, str] = {}

class ChatPayload(BaseModel):
    message: str
    provider: str = "openai"
    model: str = ""

class ProviderSelectPayload(BaseModel):
    provider: str
    model: str

@app.get("/api/state")
def api_state():
    return {"state": state(), "history": history(), "tasks": load_tasks()}

@app.get("/api/env")
def api_get_env():
    """Returns raw .env file text and parsed dictionary."""
    content = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    return {"raw": content, "dict": get_all_env_dict()}

@app.post("/api/env")
def api_save_env(payload: EnvUpdatePayload):
    """Saves raw .env text directly from editor."""
    if payload.env_content:
        ENV_FILE.write_text(payload.env_content.strip() + "\n", encoding="utf-8")
        try:
            os.chmod(ENV_FILE, 0o600)
        except Exception:
            pass
        load_env_file()
        return {"ok": True, "message": "Environment configuration saved."}
    elif payload.env_dict:
        update_env(payload.env_dict)
        return {"ok": True, "message": "Environment dictionary saved."}
    return JSONResponse({"ok": False, "error": "No content provided"}, status_code=400)

@app.get("/api/backup/download")
def api_backup_download():
    zip_path = make_backup_zip()
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")

@app.post("/api/backup/restore")
async def api_backup_restore(file: UploadFile = File(...)):
    dest = BACKUP_DIR / f"restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    res = restore_from_zip(dest)
    return res

@app.post("/api/provider/select")
def select_provider(payload: ProviderSelectPayload):
    update_env({"ACTIVE_AI_PROVIDER": payload.provider, "ACTIVE_AI_MODEL": payload.model})
    return {"ok": True, "provider": payload.provider, "model": payload.model}

@app.post("/api/notifications/test")
def notification_test():
    from .worker import send_notifications
    return {"ok": True, "results": send_notifications("Orbit Assistant test notification successfully sent.")}

@app.post("/api/tasks")
def create_task(payload: TaskPayload):
    tasks = load_tasks()
    task = payload.model_dump()
    task["id"] = uuid.uuid4().hex[:10]
    tasks.append(task)
    save_tasks(tasks)
    return task

@app.put("/api/tasks/{task_id}")
def update_task(task_id: str, payload: TaskPayload):
    tasks = load_tasks()
    updated = payload.model_dump()
    updated["id"] = task_id
    for i, task in enumerate(tasks):
        if task["id"] == task_id:
            tasks[i] = updated
            save_tasks(tasks)
            return updated
    return JSONResponse({"error": "Task not found"}, status_code=404)

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str):
    save_tasks([t for t in load_tasks() if t["id"] != task_id])
    return {"ok": True}

@app.post("/api/tasks/{task_id}/run")
def run_task_now(task_id: str):
    from .worker import run_task
    threading.Thread(target=run_task, args=(task_id,), daemon=True).start()
    return {"ok": True, "message": "Task queued"}

def _compat_models(base: str, key: str, fallback: list[str]) -> list[str]:
    if not key:
        return fallback
    try:
        headers = {"Authorization": "Bearer " + key}
        if "openrouter.ai" in base:
            headers["HTTP-Referer"] = "https://orbit-assistant.app"
        response = requests.get(base.rstrip("/") + "/models", headers=headers, timeout=15)
        response.raise_for_status()
        items = response.json().get("data", [])
        names = [item.get("id") for item in items if item.get("id")]
        return names[:80] or fallback
    except Exception:
        return fallback

@app.get("/api/ai/models")
def ai_models():
    providers_out = []
    for p in FREE_PROVIDERS:
        key = env_value(p["key_env"])
        connected = bool(key)
        if p["id"] == "custom":
            base = env_value("CUSTOM_AI_BASE_URL", "")
            connected = bool(base and key)
            models = _compat_models(base, key, [env_value("CUSTOM_AI_MODEL", "custom-model")]) if connected else []
        elif p["id"] == "openai":
            base = env_value("OPENAI_BASE_URL") or env_value("OPENAI_API_BASE") or p["base_url"]
            models = _compat_models(base, key, p["free_models"]) if connected else p["free_models"]
        elif p["id"] in ("anthropic", "gemini"):
            models = p["free_models"]
        elif p["base_url"]:
            models = _compat_models(p["base_url"], key, p["free_models"]) if connected else p["free_models"]
        else:
            models = p["free_models"]

        providers_out.append({
            "id": p["id"],
            "name": p["name"],
            "free": p.get("free", False),
            "connected": connected,
            "key_env": p["key_env"],
            "models": models,
            "base_url": p.get("base_url") or "",
        })

    active_provider = env_value("ACTIVE_AI_PROVIDER", "")
    active_model = env_value("ACTIVE_AI_MODEL", "")
    return {"providers": providers_out, "active_provider": active_provider, "active_model": active_model}

def ai_request(provider: str, model: str, message: str, use_system: bool = False):
    system = AI_SYSTEM_PROMPT if use_system else ""

    if provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        key = env_value("ANTHROPIC_API_KEY")
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        data: dict = {
            "model": model or "claude-3-5-haiku-latest",
            "max_tokens": 1200,
            "messages": [{"role": "user", "content": message}]
        }
        if system:
            data["system"] = system
        if not key:
            raise RuntimeError("Anthropic API key not configured.")
        r = requests.post(url, headers=headers, json=data, timeout=60)
        r.raise_for_status()
        return r.json()["content"][0]["text"]

    elif provider == "gemini":
        key = env_value("GEMINI_API_KEY")
        model = model or "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        headers = {"content-type": "application/json"}
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": system}]})
        contents.append({"role": "user", "parts": [{"text": message}]})
        data = {"contents": contents}
        if not key:
            raise RuntimeError("Gemini API key not configured.")
        r = requests.post(url, headers=headers, json=data, timeout=60)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    else:
        if provider == "openrouter":
            base = "https://openrouter.ai/api/v1"
            key = env_value("OPENROUTER_API_KEY")
            extra_headers = {"HTTP-Referer": "https://orbit-assistant.app", "X-Title": "Orbit Assistant"}
        elif provider == "groq":
            base = "https://api.groq.com/openai/v1"
            key = env_value("GROQ_API_KEY")
            extra_headers = {}
        elif provider == "together":
            base = "https://api.together.xyz/v1"
            key = env_value("TOGETHER_API_KEY")
            extra_headers = {}
        elif provider == "custom":
            base = env_value("CUSTOM_AI_BASE_URL", "https://api.openai.com/v1")
            key = env_value("CUSTOM_AI_API_KEY")
            extra_headers = {}
        else:
            base = env_value("OPENAI_BASE_URL") or env_value("OPENAI_API_BASE") or "https://api.openai.com/v1"
            key = env_value("OPENAI_API_KEY")
            extra_headers = {}

        if not key:
            raise RuntimeError(f"{provider} API key not found. Add {provider.upper()}_API_KEY in Environment Settings.")
        url = base.rstrip("/") + "/chat/completions"
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json", **extra_headers}
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": message})

        fallback_model = env_value("CUSTOM_AI_MODEL", "custom-model") if provider == "custom" else env_value("OPENAI_MODEL", "gpt-4o-mini")
        data = {"model": model or fallback_model, "messages": messages, "max_tokens": 1200}
        r = requests.post(url, headers=headers, json=data, timeout=60)
        r.raise_for_status()
        body = r.json()
        if not body.get("choices"):
            raise RuntimeError(f"{provider} returned no choices: {json.dumps(body, ensure_ascii=False)[:600]}")
        return body["choices"][0]["message"]["content"]

@app.post("/api/ai/chat")
def ai_chat(payload: ChatPayload):
    provider = payload.provider or env_value("ACTIVE_AI_PROVIDER", "openai")
    model = payload.model or env_value("ACTIVE_AI_MODEL", "")
    try:
        return {"ok": True, "reply": ai_request(provider, model, payload.message, use_system=True)}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

@app.post("/api/ai/test")
def ai_test(payload: ChatPayload):
    try:
        return {"ok": True, "reply": ai_request(payload.provider, payload.model, "Test connection response: OK")}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

@app.get("/api/ai/active")
def ai_active():
    return {
        "provider": env_value("ACTIVE_AI_PROVIDER", ""),
        "model": env_value("ACTIVE_AI_MODEL", ""),
    }

@app.get("/health")
def health():
    return {"ok": True, "service": "orbit-browser-assistant"}

@app.get("/screenshot")
def screenshot():
    files = sorted(SCREENSHOT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return FileResponse(files[0]) if files else JSONResponse({"error": "No screenshots available."}, status_code=404)

@app.get("/screenshot/{filename}")
def screenshot_by_name(filename: str):
    path = SCREENSHOT_DIR / filename
    return FileResponse(path) if path.exists() else JSONResponse({"error": "Not found"}, status_code=404)
