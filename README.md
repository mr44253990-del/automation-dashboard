# Orbit Browser Assistant

A reusable Python + Playwright + cron browser assistant. The default task logs into Vyce AI, opens **Daily Rewards**, claims the daily reward when available, and reports `already_done` when the site says it was already claimed. A second task can check Available Balance. More task handlers can be added in `app/worker.py`.

## Features

- Daily Rewards claim flow with duplicate-claim protection
- Multiple independent tasks, each with its own URL, time, timezone, enable switch, and screenshot retention
- Custom browser tasks using JSON steps such as `goto`, `click`, `click_text`, `fill`, `wait`, `extract_text`, and `screenshot`; values can safely reference `${TARGET_EMAIL}`-style environment placeholders
- Asia/Dhaka is the default timezone
- Screenshots are kept for a configurable number of hours and auto-deleted by the worker
- Telegram, generic webhook, and Firebase Cloud Messaging HTTP v1 notification configuration using service-account JSON plus a device token; no FCM server key is required
- Google service-account JSON can be stored server-side for a future Firebase adapter
- AI provider registry for OpenAI-compatible, Anthropic, Gemini, and custom endpoints, including live model discovery and visible connection-test results
- AI model test and chat panel
- Credentials and provider keys stay in `.env`; no secrets are rendered back in the UI
- CAPTCHA/MFA is not bypassed; the worker reports a clear failure instead

## Local setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
chmod 600 .env
# set TARGET_EMAIL and TARGET_PASSWORD only in .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`. The dashboard starts with scheduled automation OFF. Test the Daily Rewards task with the Run button, then enable the task and the global switch only after confirming the result.

## Scheduler

Run `scheduler.py` once per minute from cron. It checks every enabled task using its own `time` and IANA timezone, so one task can run at 08:00 and another at 20:17. The included `deploy.example` contains the cron line. A persistent VPS, container host, or always-on server is required for unattended daily execution; a temporary sandbox URL is not a durable scheduler.

## Notifications

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` for Telegram, or `WEBHOOK_URL` for a generic webhook. FCM fields are available in Settings and are stored server-side. Do not put secrets in task names, URLs, or notifications.

## AI

Add the desired provider key in `.env`, then use **AI providers** to test a model and **AI assistant** to chat. The chat endpoint uses provider credentials server-side. AI is an assistant, not a credential bypass; browser tasks still use explicit configured handlers and should be reviewed before enabling.

## Hosting

The Dockerfile works on container-capable hosting. Before exposing the dashboard publicly, put it behind HTTPS and authentication; the demo dashboard is intentionally lightweight and does not include user accounts. Rotate credentials that were pasted into chat before production use.
