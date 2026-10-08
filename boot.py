"""راه‌انداز بروزرسانی با فایل. باید اولین import توی main.py باشه.

نسخه‌ی بروزرسانی‌شده توی CODE_DIR (پیش‌فرض /data/code) نگه داشته می‌شه و روی کد ریپو اولویت داره.
محافظ‌ها:
 • اگه نسخه‌ی جدید دو بار پشت‌سرهم قبل از «سالم‌شدن» بالا نیومد ← قرنطینه و برگشت به نسخه‌ی قبلی.
 • اگه ریپو (GitHub) دوباره دیپلوی شده باشه، نسخه‌ی بروزرسانی‌شده کهنه حساب می‌شه و کنار گذاشته می‌شه.
"""
import os
import sys
import json
import shutil
import hashlib

REPO_DIR = os.environ.setdefault("SELF_REPO_DIR", os.path.dirname(os.path.abspath(__file__)))
CODE_DIR = os.getenv("CODE_DIR", "/data/code")
STATE = CODE_DIR.rstrip("/") + ".state"
NOTE = os.getenv("UPDATE_NOTE_FILE", "/data/update_note.json")
CODE_FILES = ("main.py", "core.py", "features.py", "meow.py", "botpanel.py", "updater.py", "boot.py", "ctl.py", "hub.py", "extras.py", "railway.py")
MAX_TRIES = 2


def fingerprint(directory: str) -> str:
    h = hashlib.sha256()
    for n in CODE_FILES:
        try:
            with open(os.path.join(directory, n), "rb") as f:
                h.update(n.encode() + f.read())
        except OSError:
            h.update(n.encode() + b"-")
    return h.hexdigest()


def _read(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(path, data):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError:
        pass


def _quarantine(reason: str):
    dst = CODE_DIR.rstrip("/") + ".bad"
    shutil.rmtree(dst, ignore_errors=True)
    try:
        os.replace(CODE_DIR, dst)
    except OSError:
        shutil.rmtree(CODE_DIR, ignore_errors=True)
    try:
        os.remove(STATE)
    except OSError:
        pass
    _write(NOTE, {"msg": reason})
    print("[boot]", reason, flush=True)


def healthy():
    """بعد از چند ثانیه‌ی بدون مشکل صدا زده می‌شه؛ شمارنده‌ی تلاش صفر می‌شه."""
    if os.path.isdir(CODE_DIR):
        _write(STATE, {"tries": 0, "base": _read(STATE, {}).get("base", "")})


def _prepare():
    if not os.path.isdir(CODE_DIR) or not any(n.endswith(".py") for n in os.listdir(CODE_DIR)):
        return None
    st = _read(STATE, {})
    base = fingerprint(REPO_DIR)
    if st.get("base") and st["base"] != base:
        _quarantine("ℹ️ ریپو دوباره دیپلوی شده؛ نسخه‌ی بروزرسانی‌شده‌ی قبلی کنار گذاشته شد و نسخه‌ی GitHub اجرا می‌شه.")
        return None
    if int(st.get("tries", 0)) >= MAX_TRIES:
        _quarantine("⚠️ نسخه‌ی بروزرسانی‌شده بالا نیومد؛ خودکار به نسخه‌ی قبلی برگشتم.")
        return None
    _write(STATE, {"tries": int(st.get("tries", 0)) + 1, "base": st.get("base") or base})
    return CODE_DIR


def _bootstrap():
    if os.environ.get("SELF_OVERLAY"):
        return  # همین الان از نسخه‌ی بروزرسانی‌شده اجرا شدیم
    code = _prepare()
    if not code:
        return
    os.environ["SELF_OVERLAY"] = "1"
    if os.path.isfile(os.path.join(code, "main.py")):
        env = dict(os.environ)
        env["PYTHONPATH"] = REPO_DIR + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        try:
            os.execve(sys.executable, [sys.executable, os.path.join(code, "main.py")], env)
        except OSError as e:
            print("[boot] exec failed:", e, flush=True)
    if code not in sys.path:  # فقط بعضی ماژول‌ها بروزرسانی شدن
        sys.path.insert(0, code)


_bootstrap()
