from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "data"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "credentials": {
        "email": "",
        "password": "",
        "login_url": "https://vyceai.com/login",
        "target_url": "https://vyceai.com/dashboard-v2"
    },
    "automation": {
        "enabled": False,
        "headless": True,
        "timezone": "Asia/Dhaka",
        "screenshot_retention_hours": 12
    },
    "ai": {
        "active_provider": "",
        "active_model": "",
        "providers": {}
    },
    "telegram": {
        "bot_token": "",
        "chat_id": ""
    },
    "notifications": {
        "webhook_url": "",
        "fcm_token": "",
        "google_service_account_json": ""
    },
    "browser": {
        "auto_hide_popups": True,
        "smart_interaction": True,
        "show_mouse_movement": True
    },
    "ui": {
        "theme": "dark",
        "live_view_enabled": True
    }
}


def ensure_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG.copy())


def load_config() -> dict[str, Any]:
    ensure_config()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge with defaults
        merged = DEFAULT_CONFIG.copy()
        _deep_merge(merged, data)
        return merged
    except Exception:
        return DEFAULT_CONFIG.copy()


def _deep_merge(base, override):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def save_config(config: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except Exception:
        pass


def get_config_value(path: str, default: Any = None) -> Any:
    cfg = load_config()
    keys = path.split(".")
    cur = cfg
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur


def set_config_value(path: str, value: Any) -> None:
    cfg = load_config()
    keys = path.split(".")
    cur = cfg
    for k in keys[:-1]:
        if k not in cur or not isinstance(cur[k], dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value
    save_config(cfg)
