import json
import os

SETTINGS_FILE = os.path.expanduser('~/projects/homelab-dashboard/settings.json')
MASKED_KEYS = ['geminiApiKey', 'anthropicApiKey', 'openaiApiKey']


def get_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, 'r') as f:
        data = json.load(f)
    for k in MASKED_KEYS:
        if k in data and data[k]:
            data[k] = data[k][:8] + '*' * 20
    return data


def save_settings(data: dict) -> None:
    current = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                current = json.load(f)
        except Exception:
            pass

    for k, v in data.items():
        if '*' not in str(v):
            current[k] = v

    with open(SETTINGS_FILE, 'w') as f:
        json.dump(current, f, indent=2)
