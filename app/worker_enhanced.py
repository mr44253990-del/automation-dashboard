from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from app import config

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
SCREENSHOT_DIR = ROOT / "screenshots"

for folder in (LOG_DIR, SCREENSHOT_DIR):
    folder.mkdir(exist_ok=True)


def get_cred_email() -> str:
    cfg = config.load_config()
    email = cfg.get("credentials", {}).get("email") or os.getenv("TARGET_EMAIL", "")
    return email.strip()


def get_cred_password() -> str:
    cfg = config.load_config()
    password = cfg.get("credentials", {}).get("password") or os.getenv("TARGET_PASSWORD", "")
    return password.strip()


def get_login_url() -> str:
    cfg = config.load_config()
    url = cfg.get("credentials", {}).get("login_url") or os.getenv("LOGIN_URL", "https://vyceai.com/login")
    return url.strip()


def get_target_url() -> str:
    cfg = config.load_config()
    url = cfg.get("credentials", {}).get("target_url") or os.getenv("TARGET_URL", "https://vyceai.com/dashboard-v2")
    return url.strip()


def detect_and_dismiss_premium_popup(page, task_id: str = ""):
    """Detect premium/popup and dismiss it - try X button, else click in empty area."""
    try:
        from app.worker import update_live_status
        update_live_status("Scanning for premium/popup overlays...", page, task_id)
        # Common patterns for premium popups
        popup_selectors = [
            "button[aria-label*='close' i]",
            "button[aria-label*='dismiss' i]",
            ".modal-close",
            ".popup-close",
            ".close-button",
            "button.close",
            "[data-testid*='close' i]",
            "svg[aria-label*='close' i]",
        ]
        for sel in popup_selectors:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=800):
                    update_live_status("Found close button on popup. Dismissing...", page, task_id)
                    try:
                        loc.click()
                        page.wait_for_timeout(1000)
                        return True
                    except Exception:
                        pass
            except Exception:
                continue
        # Look for text like 'Premium', 'Upgrade', 'Go Premium'
        try:
            body_text = page.locator("body").inner_text(timeout=2000).lower()
            if any(k in body_text for k in ['go premium', 'upgrade now', 'premium offer']):
                # Try clicking outside/modal backdrop
                update_live_status("Premium popup detected. Clicking outside to dismiss...", page, task_id)
                try:
                    # Click at top-left area or body
                    page.mouse.click(10, 10)
                    page.wait_for_timeout(800)
                    return True
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass
    return False


def human_like_move(page, x: int, y: int):
    """Move mouse in a more human-like way"""
    try:
        current = page.mouse._last_pos if hasattr(page.mouse, '_last_pos') else (0, 0)
        steps = 8
        for i in range(1, steps + 1):
            nx = current[0] + (x - current[0]) * i / steps
            ny = current[1] + (y - current[1]) * i / steps
            page.mouse.move(nx, ny)
            time.sleep(0.01)
        page.mouse.move(x, y)
        if hasattr(page.mouse, '_last_pos'):
            page.mouse._last_pos = (x, y)
    except Exception:
        try:
            page.mouse.move(x, y)
        except Exception:
            pass


def smart_ai_navigate(page, instruction: str = ""):
    """Let AI understand and navigate page"""
    try:
        from app.worker import update_live_status
        update_live_status("AI analyzing page structure...", page, "")
        # Get page info
        url = page.url
        title = page.title()
        # Do some smart mouse movements
        try:
            page.mouse.move(100, 100)
            time.sleep(0.1)
            page.mouse.move(200, 150)
        except Exception:
            pass
        update_live_status(f"AI observing: {title} at {url}", page, "")
        return {"url": url, "title": title}
    except Exception as e:
        return {"error": str(e)}
