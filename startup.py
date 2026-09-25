"""Per-user Windows sign-in startup, shared with the desktop Settings UI."""
import json
import os
import subprocess
import sys
from pathlib import Path

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_NAME = 'ToriDownload'


def read_config(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(path, changes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    config = read_config(path)
    config.update(changes)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(config), encoding='utf-8')
    os.replace(temporary, path)


def startup_enabled(path, default=True):
    return read_config(path).get('launch_on_login', default) is True


def startup_command():
    if getattr(sys, 'frozen', False):
        parts = [str(Path(sys.executable).resolve()), '--background']
    else:
        python = Path(sys.executable).resolve()
        if os.name == 'nt' and python.name.lower() == 'python.exe' and python.with_name('pythonw.exe').exists():
            python = python.with_name('pythonw.exe')
        parts = [str(python), str(Path(__file__).resolve().parent / 'app.py'), '--background']
    return subprocess.list2cmdline(parts)


def sync_startup(path, enabled=None, default=True, run_name=RUN_NAME):
    """Update this user's Run entry; save the preference only after success."""
    if os.name != 'nt':
        if enabled is not None:
            raise OSError('Windows sign-in startup is only available on Windows.')
        return
    import winreg
    use_startup = startup_enabled(path, default) if enabled is None else enabled
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if use_startup:
            winreg.SetValueEx(key, run_name, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, run_name)
            except FileNotFoundError:
                pass
    if enabled is not None:
        save_config(path, {'launch_on_login': bool(enabled)})
