from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json, os
from app.worker import load_tasks, run_task, ROOT

STATE = ROOT / 'logs' / 'schedule_state.json'
def load_state():
    try: return json.loads(STATE.read_text())
    except Exception: return {}
def save_state(v): STATE.write_text(json.dumps(v, indent=2))

def main():
    if os.getenv('AUTOMATION_ENABLED', 'false').lower() != 'true':
        print('Automation is OFF; no scheduled tasks executed.')
        return
    state = load_state(); changed = False
    for task in load_tasks():
        if not task.get('enabled'): continue
        zone = ZoneInfo(task.get('timezone', 'Asia/Dhaka'))
        now = datetime.now(zone); due = task.get('time', '20:17')
        if now.strftime('%H:%M') != due: continue
        key = f"{task['id']}:{now.date().isoformat()}"
        if state.get(task['id']) == key: continue
        print(f"Running {task['name']} at {now.isoformat()}")
        run_task(task['id']); state[task['id']] = key; changed = True
    if changed: save_state(state)
if __name__ == '__main__': main()
