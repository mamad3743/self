"""هاب چندکاربره: یه بات مشترک برای همه. هر کس اکانت خودش رو وصل می‌کنه و سلفش خودکار ساخته و روی همین سرور اجرا می‌شه.

بدون توکن و بدون بات جدا: کاربر فقط /start می‌زنه ← «ساخت سلف من» ← شماره ← کد ← (رمز دومرحله‌ای) ← سلف آماده‌ست.
ورود: داخل بات (شماره/QR) یا صفحه‌ی وب. بعدش: پنل قابلیت‌ها + بازی میویی، روشن/خاموش/ریستارت،
پشتیبان‌گیری کامل و بازیابی، و مینی‌اپ (WebApp) برای هر نفر.

فعال‌سازی (متغیرهای Railway):
  HUB_BOT_TOKEN = توکن بات مشترک (BotFather)      HUB_ADMIN_ID = آیدی عددی تو (ادمین)
  API_ID / API_HASH = اختیاری (از my.telegram.org)  MAX_USERS = سقف کاربر (پیش‌فرض ۵)
  HUB_OPEN = 1/0 ثبت‌نام باز (پیش‌فرض ۱: هر کس خودکار ثبت می‌شه؛ ۰ = فقط با تأیید ادمین)
  HUB_TRIAL_DAYS = دوره‌ی آزمایشی کاربر جدید به روز (پیش‌فرض ۰ = نامحدود)
  HUB_DIR = پوشه‌ی داده (پیش‌فرض /data/hub)   PROXY = اختیاری
  MAX_RSS_MB = سقف رم هر سلف (۰ = بدون سقف)   BACKUP_HOURS = فاصله‌ی بکاپ خودکار (پیش‌فرض ۲۴)
  HUB_DOMAIN = دامنه‌ی عمومی Railway (مثل xxx.up.railway.app) برای مینی‌اپ و ورود وب (اختیاری)

هر کاربر: /data/hub/<id>/ شامل session.txt، settings.json، ctl.jsonl (صف دستور)، status.json.
دستورهای نقطه‌ای (.میویی و...) توی چت‌های خود کاربر مثل قبل کار می‌کنن؛ بات برای اتصال، پنل، وضعیت و مدیریته.
"""
import io
import base64
import os
import re
import sys
import json
import time
import hmac
import html
import hashlib
import datetime
import shutil
import signal
import socket
import asyncio
import secrets
import zipfile
import tempfile
import collections
import urllib.parse

os.environ.setdefault("PANEL_PASSWORD", secrets.token_hex(12))  # core موقع import لازم داره

import aiohttp
from aiohttp import web
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, PhoneNumberInvalidError,
    PasswordHashInvalidError, FloodWaitError, ApiIdInvalidError, PhoneNumberBannedError, PhoneNumberFloodError,
    SendCodeUnavailableError,
)
from telethon.tl.functions.auth import ResendCodeRequest

import boot
import core
import botpanel
import weblogin
import meow
import updater
import miniapp
from core import FEATS, FEAT, GRID, log

REPO = os.environ.get("SELF_REPO_DIR") or os.path.dirname(os.path.abspath(__file__))
DEFAULT_FLAGS = dict(core.F)  # پیش‌فرض قابلیت‌ها (قبل از هر load_settings)
HIDDEN = {"update"}  # از پنل کاربرها مخفیه

TOKEN = ""
ADMIN = 0
DATA = "/data/hub"
MAX_USERS = 5
MAX_RSS_MB = 0
BACKUP_HOURS = 24
BACKUP_KEEP = 7
DAY = 86400
API_ID = 0
API_HASH = ""
DOMAIN = ""
INSTANCES = {}
LOGIN = {}  # uid -> وضعیت مراحل ورود
REQ_TS = {}  # uid -> زمان آخرین درخواست دسترسی
LOGIN_TTL = 600
SNIPPET = (
    "# SELF_HUB_CHILD\n"  # برچسب برای پیدا کردن سلف‌های یتیم توی kill_stale
    "import sys, os, runpy\n"
    "code = os.environ.get('HUB_CODE_DIR') or ''\n"
    "repo = os.environ['SELF_REPO_DIR']\n"
    "sys.path[:0] = [p for p in (code, repo) if p]\n"
    "main = os.path.join(code, 'main.py') if code and os.path.isfile(os.path.join(code, 'main.py')) else os.path.join(repo, 'main.py')\n"
    "sys.argv = [main]\n"
    "runpy.run_path(main, run_name='__main__')\n"
)


TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")


def clean_token(raw: str) -> str:
    """توکن BotFather رو تمیز می‌کنه: فاصله، خط جدید، گیومه و پیشوند «bot» که موقع paste توی Railway همراهش میاد
    (دلیل رایج «توکن قبول نمی‌شه»)."""
    t = (raw or "").strip().strip("\"'`").strip()
    t = re.sub(r"\s+", "", t)
    if t.lower().startswith("bot") and ":" in t[3:]:
        t = t[3:]
    return t


def configure(env=None):
    global TOKEN, ADMIN, DATA, MAX_USERS, API_ID, API_HASH, MAX_RSS_MB, BACKUP_HOURS, DOMAIN, OPEN_DEFAULT, TRIAL_DEFAULT
    env = env if env is not None else os.environ
    TOKEN = clean_token(env.get("HUB_BOT_TOKEN", ""))
    ADMIN = int(re.sub(r"\D", "", env.get("HUB_ADMIN_ID") or "") or 0)
    OPEN_DEFAULT = (env.get("HUB_OPEN", "1").strip() not in ("0", "false", "False", "no", "off"))
    TRIAL_DEFAULT = int(re.sub(r"\D", "", env.get("HUB_TRIAL_DAYS") or "") or 0)
    DATA = env.get("HUB_DIR", "/data/hub")
    MAX_USERS = int(env.get("MAX_USERS") or 5)
    MAX_RSS_MB = int(env.get("MAX_RSS_MB") or 0)
    BACKUP_HOURS = int(env.get("BACKUP_HOURS") or 24)
    DOMAIN = (env.get("HUB_DOMAIN") or env.get("RAILWAY_PUBLIC_DOMAIN") or "").strip().rstrip("/")
    if DOMAIN and not DOMAIN.startswith("http"):
        DOMAIN = "https://" + DOMAIN
    if TOKEN and not TOKEN_RE.match(TOKEN):
        log.warning("HUB_BOT_TOKEN قالب معتبری نداره (باید مثل 123456789:AAH... باشه)؛ از BotFather دوباره کپی کن.")
    core.load_api()
    API_ID = int(env.get("API_ID") or 0) or core.API["id"]
    API_HASH = env.get("API_HASH") or core.API["hash"]
    os.makedirs(DATA, exist_ok=True)


def app_base_url() -> str:
    """آدرس پایه‌ی مینی‌اپ (خالی = مینی‌اپ غیرفعال)."""
    return (DOMAIN.rstrip("/") + "/app") if DOMAIN else ""


# ───────────── ذخیره‌سازی ─────────────
def num(t):
    return meow.num(t)


def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def udir(uid):
    return os.path.join(DATA, str(uid))


def upath(uid, name):
    return os.path.join(udir(uid), name)


def load_reg():
    reg = read_json(os.path.join(DATA, "users.json"), {})
    reg.setdefault("allowed", {})
    return reg


def save_reg(reg):
    write_json(os.path.join(DATA, "users.json"), reg)


def get_entry(uid):
    return load_reg()["allowed"].get(str(uid))


def is_allowed(uid) -> bool:
    if uid == ADMIN:
        return True
    e = get_entry(uid)
    if e is None:
        return False
    exp = e.get("expires", 0)
    return exp == 0 or exp > time.time()


def days_left(uid):
    """None = نامحدود؛ وگرنه تعداد روز مونده (گرد به بالا)."""
    e = get_entry(uid)
    exp = (e or {}).get("expires", 0)
    return None if not exp else max(0, -(-int(exp - time.time()) // DAY))


def sub_text(uid) -> str:
    if uid == ADMIN:
        return "♾ ادمین"
    d = days_left(uid)
    return "♾ نامحدود" if d is None else (f"⌛ منقضی شده" if not is_allowed(uid) else f"📅 {d} روز مونده")


def allow_user(target, name="", days=0):
    unban_user(target)
    reg = load_reg()
    old = reg["allowed"].get(str(target), {})
    reg["allowed"][str(target)] = {
        "name": name or old.get("name", ""), "since": old.get("since", int(time.time())),
        "expires": int(time.time() + days * DAY) if days > 0 else 0}
    save_reg(reg)


def extend_user(target, days) -> bool:
    """مدت اشتراک رو زیاد می‌کنه (از انقضای فعلی یا از الان) و هشدارها/وضعیت منقضی رو ریست می‌کنه."""
    reg = load_reg()
    e = reg["allowed"].get(str(target))
    if e is None or days <= 0:
        return False
    base = max(time.time(), e.get("expires", 0) or 0)
    e["expires"] = int(base + days * DAY)
    for k in ("expired", "warn1", "warn3"):
        e.pop(k, None)
    save_reg(reg)
    return True


def has_session(uid) -> bool:
    try:
        return bool(open(upath(uid, "session.txt")).read().strip())
    except OSError:
        return False


def connected_users():
    out = []
    try:
        for name in os.listdir(DATA):
            if name.isdigit() and has_session(int(name)):
                out.append(int(name))
    except OSError:
        pass
    return out


def read_flags(uid) -> dict:
    feats = read_json(upath(uid, "settings.json"), {}).get("features", {})
    return {k: bool(feats.get(k, v)) for k, v in DEFAULT_FLAGS.items()}


def read_status(uid) -> dict:
    return read_json(upath(uid, "status.json"), {})


def ctl_send(uid, **op):
    os.makedirs(udir(uid), exist_ok=True)
    with open(upath(uid, "ctl.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(op, ensure_ascii=False) + "\n")


def set_flag(uid, key, value) -> bool:
    """قابلیت رو روشن/خاموش می‌کنه: اگه سلف در حال اجراست از صف فرمان، وگرنه مستقیم توی تنظیماتش."""
    if key not in DEFAULT_FLAGS or key in HIDDEN:
        return False
    inst = INSTANCES.get(uid)
    if inst and inst.running:
        ctl_send(uid, op="toggle", key=key, value=bool(value))
    else:
        data = read_json(upath(uid, "settings.json"), {})
        data.setdefault("features", {})[key] = bool(value)
        data.setdefault("cfg", {})
        write_json(upath(uid, "settings.json"), data)
    return True


# ───────────── اجرای سلف هر کاربر ─────────────
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _preexec():
    try:  # اگه هاب بمیره، سلف‌ها هم بمیرن (جلوگیری از دو کلاینت با یه سشن)
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)
    except Exception:  # noqa
        pass


def panel_password(uid) -> str:
    p = upath(uid, "panel_pw")
    try:
        return open(p).read().strip()
    except OSError:
        pw = secrets.token_hex(12)
        os.makedirs(udir(uid), exist_ok=True)
        with open(p, "w") as f:
            f.write(pw)
        return pw


def child_env(uid) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("HUB_BOT_TOKEN", "HUB_ADMIN_ID", "BOT_TOKEN", "SESSION_STRING", "PORT", "SETTINGS_FILE")}
    env.update(
        HUB_INSTANCE="1", SELF_REPO_DIR=REPO, SELF_OVERLAY="1",
        API_FILE=upath(uid, "api.json"), SESSION_FILE=upath(uid, "session.txt"),
        SETTINGS_FILE=upath(uid, "settings.json"), CTL_FILE=upath(uid, "ctl.jsonl"),
        STATUS_FILE=upath(uid, "status.json"), ALERT_FILE=upath(uid, "alerts.jsonl"), PORT=str(free_port()), PANEL_PASSWORD=panel_password(uid),
        API_ID=str(API_ID), API_HASH=API_HASH, PYTHONUNBUFFERED="1",
    )
    # اگه هاب با نسخه‌ی بروزرسانی‌شده (/data/code) بالا اومده، سلف‌ها هم همونو اجرا کنن
    if os.environ.get("SELF_OVERLAY") and os.path.isdir(boot.CODE_DIR):
        env["HUB_CODE_DIR"] = boot.CODE_DIR
    else:
        env.pop("HUB_CODE_DIR", None)
    return env


def rss_mb(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError):
        pass
    return None


class Instance:
    def __init__(self, uid):
        self.uid = uid
        self.proc = None
        self.task = None
        self.stopping = False
        self.failed = False
        self.started = 0.0
        self.crashes = []
        self.logs = collections.deque(maxlen=60)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def rss(self):
        return rss_mb(self.proc.pid) if self.running and getattr(self.proc, "pid", None) else None

    def start(self):
        if self.task and not self.task.done():
            return
        self.stopping = self.failed = False
        self.task = asyncio.create_task(self._supervise())

    async def _supervise(self):
        while not self.stopping:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa
                log.warning("[u%s] spawn failed: %r", self.uid, e)
                self.logs.append(f"spawn failed: {e!r}")
            if self.stopping:
                return
            now = time.time()
            self.crashes = [t for t in self.crashes if now - t < 600] + [now]
            if len(self.crashes) > 5:
                self.failed = True
                self.logs.append("⚠️ بیش از ۵ بار در ۱۰ دقیقه کرش کرد؛ متوقف شد")
                log.error("[u%s] too many crashes; giving up", self.uid)
                asyncio.create_task(notify_failed(self.uid))
                return
            await asyncio.sleep(min(60, 5 * len(self.crashes)))

    async def _run_once(self):
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", SNIPPET, cwd=REPO, env=child_env(self.uid),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, preexec_fn=_preexec)
        self.proc, self.started = proc, time.time()
        with open(upath(self.uid, "pid"), "w") as f:
            f.write(str(proc.pid))
        log.info("[u%s] started pid=%s", self.uid, proc.pid)
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", "ignore").rstrip()
            self.logs.append(text)
            print(f"[u{self.uid}] {text}", flush=True)
        await proc.wait()
        try:
            os.remove(upath(self.uid, "pid"))
        except OSError:
            pass
        log.info("[u%s] exited code=%s", self.uid, proc.returncode)

    async def stop(self, timeout=8):
        self.stopping = True
        proc = self.proc
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        if self.task:
            try:
                await asyncio.wait_for(self.task, 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.task.cancel()
            except Exception:  # noqa
                pass


def get_instance(uid) -> Instance:
    return INSTANCES.setdefault(uid, Instance(uid))


def stopped_marker(uid) -> str:
    return upath(uid, "stopped")


def kill_stale():
    """اگه هاب قبلی مرده ولی سلف‌ها مونده باشن، می‌کشیمشون تا یه سشن دو بار وصل نشه."""
    try:
        names = os.listdir(DATA)
    except OSError:
        return
    for name in names:
        p = os.path.join(DATA, name, "pid")
        try:
            pid = int(open(p).read().strip())
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read()
        except (OSError, ValueError):
            try:
                os.remove(p)
            except OSError:
                pass
            continue
        if b"SELF_HUB_CHILD" in cmd:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(1.5)
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        try:
            os.remove(p)
        except OSError:
            pass


def migrate_admin():
    """سلف تک‌کاربره‌ی قبلی (/data/session.txt) خودکار تبدیل به سلف ادمین توی هاب می‌شه (کپی؛ چیزی پاک نمی‌شه)."""
    if not ADMIN or has_session(ADMIN):
        return
    old_session = os.getenv("SESSION_FILE", "/data/session.txt")
    try:
        sess = open(old_session).read().strip()
    except OSError:
        return
    if not sess:
        return
    os.makedirs(udir(ADMIN), exist_ok=True)
    with open(upath(ADMIN, "session.txt"), "w") as f:
        f.write(sess)
    old_settings = os.getenv("SETTINGS_FILE", "/data/settings.json")
    if os.path.isfile(old_settings) and not os.path.isfile(upath(ADMIN, "settings.json")):
        shutil.copy(old_settings, upath(ADMIN, "settings.json"))
    log.info("hub: سلف قبلی ادمین منتقل شد")


async def start_all():
    for uid in connected_users():
        if os.path.exists(stopped_marker(uid)) or not is_allowed(uid):
            continue
        get_instance(uid).start()
        await asyncio.sleep(2)  # فشار همزمان روی CPU/حافظه نیاد


async def stop_all():
    await asyncio.gather(*(i.stop() for i in list(INSTANCES.values())), return_exceptions=True)


# ───────────── متن‌ها و کیبوردها ─────────────
LOOP_NAMES = {"meow": "میویی", "fish": "ماهیگیری", "fridge": "یخچال", "cat": "پیشی"}


def fmt_dur(sec) -> str:
    sec = int(sec)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return " ".join(x for x in (f"{d} روز" if d else "", f"{h} ساعت" if h else "", f"{m} دقیقه" if (m or not (d or h)) else "") if x)


def status_text(uid) -> str:
    inst = INSTANCES.get(uid)
    st = read_status(uid)
    if not has_session(uid):
        return f"🔌 هنوز اکانتی وصل نکردی. /connect\n🎫 اشتراک: {sub_text(uid)}"
    if inst and inst.failed:
        head = "⚠️ سلف چند بار کرش کرد و متوقف شد (/restart)"
    elif inst and inst.running:
        head = "🟢 سلف در حال اجراست"
    else:
        head = "🔴 سلف متوقف است (/run)"
    lines = [f"<b>{head}</b>"]
    fresh = st and time.time() - st.get("ts", 0) < 40
    if inst and inst.running:
        lines.append(f"⏱ مدت اجرا: {fmt_dur(time.time() - inst.started)}")
        if fresh:
            lines.append("📡 اتصال تلگرام: " + ("✅ وارد شده" if st.get("authorized") else "❌ وارد نشده (سشن نامعتبره؟ /disconnect و دوباره /connect)"))
        else:
            lines.append("📡 اتصال تلگرام: ⏳ در حال بالا اومدن...")
    mem = inst.rss() if inst else None
    if mem:
        lines.append(f"🧠 رم: {mem:.0f} MB")
    lines.append(f"🎫 اشتراک: {sub_text(uid)}")
    flags = read_flags(uid)
    on = [FEAT[k]["emoji"] + " " + FEAT[k]["name"] for k in FEAT if flags.get(k) and k not in HIDDEN and FEAT[k]["toggle"]]
    lines.append(f"\n🎛 قابلیت‌های روشن ({len(on)}): " + ("، ".join(on) if on else "—"))
    if fresh and st.get("loops"):
        run = "، ".join(f"{LOOP_NAMES.get(k, k)} در {n} چت" for k, n in st["loops"].items())
        lines.append(f"🔄 خودکارهای فعال: {run}")
    return "\n".join(lines)


def is_running(uid) -> bool:
    inst = INSTANCES.get(uid)
    return bool(inst and inst.running)


def main_text(uid) -> str:
    """پنل مدیریتی سلف (فقط با /panel میاد؛ با /start قاطی نمی‌شه)."""
    flags = read_flags(uid)
    on = sum(1 for k, v in flags.items() if v and k not in HIDDEN)
    total = len(FEATS) - len(HIDDEN)
    inst = INSTANCES.get(uid)
    st = read_status(uid)
    fresh = bool(st and time.time() - st.get("ts", 0) < 40)
    if inst and inst.failed:
        run = "⚠️ کرش کرده (ریستارت بزن)"
    elif inst and inst.running:
        run = f"🟢 روشن · ⏱ {fmt_dur(time.time() - inst.started)}"
    else:
        run = "🔴 خاموش"
    if fresh:
        tg = "📡 ✅" if st.get("authorized") else "📡 ❌"
    elif inst and inst.running:
        tg = "📡 ⏳"
    else:
        tg = "📡 —"
    mem = inst.rss() if inst else None
    mem_s = f" · 🧠 {mem:.0f}MB" if mem else ""
    loops_s = ""
    if fresh and st.get("loops"):
        loops_s = "\n🔄 " + " · ".join(f"{LOOP_NAMES.get(k, k)} ({n})" for k, n in st["loops"].items())
    return ("🔥 <b>پنل مدیریت سلف</b>\n"
            f"🤖 {run} {tg}{mem_s}\n"
            f"🎫 {sub_text(uid)}{loops_s}\n"
            f"🎛 <b>{on}</b> از {total} قابلیت روشن — 🟢 روشن · 🔴 خاموش · 🔵 دستوری\n\n"
            "👆 مدیریت سلف (وضعیت، روشن/خاموش، بکاپ، مینی‌اپ)\n"
            "👇 هر قابلیت رو بزن تا راهنما و نمونه دستورش رو ببینی\n"
            "🐱 دستورهای بازی (<code>.میویی</code> <code>.ماهیگیری</code> ...) رو توی همون چت بازی بزن")


def feat_style(f, flags) -> str:
    if not f["toggle"]:
        return "primary"
    return "success" if flags.get(f["key"]) else "danger"


def manage_keyboard(uid) -> list:
    """ردیف‌های مدیریتی بالای پنل: وضعیت/روشن/خاموش/ریستارت/بکاپ/مینی‌اپ/دیپلوی."""
    running = is_running(uid)
    rows = [
        [botpanel.btn("📊 وضعیت", "mg:status", "primary"),
         botpanel.btn("🔴 خاموش", "mg:stop", "danger") if running else botpanel.btn("🟢 روشن", "mg:run", "success"),
         botpanel.btn("🔄 ریستارت", "mg:restart", "primary")],
        [botpanel.btn("💾 بکاپ", "mg:backup", "primary"),
         botpanel.btn("♻️ بازیابی آخر", "mg:restore_last", "primary"),
         botpanel.btn("❓ راهنما", "mg:help", "primary")],
    ]
    url = app_base_url()
    if url:
        rows.append([{"text": "📱 باز کردن مینی‌اپ", "web_app": {"url": url}}])
    else:
        rows.append([botpanel.btn("📱 مینی‌اپ", "mg:app", "primary")])
    return rows


def main_keyboard(uid) -> dict:
    flags = read_flags(uid)
    rows = manage_keyboard(uid)
    for row in GRID:
        keys = [k for k in row if k not in HIDDEN]
        if not keys:
            continue
        btns = [botpanel.btn(f"{FEAT[k]['emoji']} {FEAT[k]['name']}", f"f:{k}", feat_style(FEAT[k], flags)) for k in keys]
        rows.append(list(reversed(btns)))
    rows.append([botpanel.btn("❌ بستن پنل", "x", "danger")])
    return {"inline_keyboard": rows}

























MINIAPP_HELP = (
    "📱 <b>مینی‌اپ سلف</b>\n\n"
    "از مینی‌اپ می‌تونی بدون دستور تایپ کردن کارت رو بکنی:\n"
    "• دیدن وضعیت و رم و آپتایم\n"
    "• روشن/خاموش/ریستارت سلف\n"
    "• روشن/خاموش کردن همه‌ی قابلیت‌ها + بازی‌ها (میویی، ماهیگیری، یخچال، پیشی، خفاش، نجات)\n"
    "• اجرای دستور توی یه چت (مثلاً <code>.میویی</code> توی گروه بازی)\n"
    "• دانلود بکاپ و آپلود برای بازیابی\n\n"
    "{app_line}\n"
    "فعال‌سازی برای ادمین: توی @BotFather دستور /newapp یا /editapp ← Web App URL رو بذار روی:\n<code>{app_url}</code>\n"
    "یا متغیر <code>HUB_DOMAIN</code> رو توی Railway ست کن تا دکمه‌ی «باز کردن مینی‌اپ» زیر پنل بیاد."
)


def feat_text(uid, key) -> str:
    f = FEAT[key]
    flags = read_flags(uid)
    on = sum(1 for k, v in flags.items() if v and k not in HIDDEN)
    if f["toggle"]:
        status = "🟢 <b>روشنه</b> — با دکمه‌ی زیر خاموشش کن" if flags.get(key) else "🔴 <b>خاموشه</b> — با دکمه‌ی زیر روشنش کن"
    else:
        status = "🔵 دستوری — روشن/خاموش نداره، با دستور اجراش کن"
    ex = "\n".join(f"<code>{html.escape(e)}</code>" for e in f["examples"])
    return (f"{f['emoji']} <b>{html.escape(f['name'])}</b>\n"
            f"{status}\n"
            f"🎛 {on} قابلیت روشنه\n\n"
            f"📖 {html.escape(f['desc'])}\n\n"
            f"⌨️ <b>نمونه دستور:</b>\n{ex}")


def feat_keyboard(key) -> dict:
    rows = []
    if FEAT[key]["toggle"]:
        rows.append([botpanel.btn("🔴 خاموش", f"t:{key}:0", "danger"), botpanel.btn("🟢 روشن", f"t:{key}:1", "success")])
    rows.append([botpanel.btn("🔙 بازگشت", "m", "primary"), botpanel.btn("❌ بستن", "x", "danger")])
    return {"inline_keyboard": rows}


HELP = (
    "🐾 <b>سلف تلگرام — یه بات برای همه</b>\n\n"
    "بات جدا نمی‌خوای، توکن هم لازم نیست: اکانتت رو وصل می‌کنی و سلف مخصوص خودت "
    "<b>خودکار روی سرور ساخته و اجرا می‌شه</b>.\n\n"
    "/start ← شروع و ساخت سلف\n"
    "/connect ← وصل کردن اکانت (شماره ← کد ← رمز دومرحله‌ای، یا QR، یا صفحه‌ی وب)\n"
    "/panel ← پنل مدیریتی (روشن/خاموش سلف، قابلیت‌ها، بازی، بکاپ، مینی‌اپ)\n"
    "/status ← وضعیت سلفت\n"
    "/app ← لینک مینی‌اپ (کنترل لمسی کامل)\n"
    "/cmd ← اجرای دستور توی یه چت، مثلاً <code>/cmd me .وضعیت چت</code> یا <code>/cmd @group .میویی</code>\n"
    "/run · /stop · /restart ← روشن / خاموش / ریستارت سلف\n"
    "/backup ← بکاپ تنظیمات · /backup_full ← بکاپ کامل (تنظیمات + سشن، زیپ)\n"
    "/restore ← بازیابی (فایل json/zip با کپشن /restore یا <code>/restore last</code>)\n"
    "/disconnect ← خروج کامل و حذف اطلاعات\n\n"
    "بعد از وصل شدن، دستورهای نقطه‌ای (<code>.میویی</code> <code>.ماهیگیری</code> <code>.یخچال</code> "
    "<code>.پیشی</code> <code>.خفاش</code> <code>.نجات</code> و...) رو توی خود تلگرامت بزن."
)
ADMIN_HELP = (
    "\n\n<b>ادمین:</b>\n/users ← لیست کاربرها (اشتراک و رم)\n/allow &lt;id&gt; [روز] [نام] ← دسترسی (بدون روز = نامحدود)\n"
    "/extend &lt;id&gt; &lt;روز&gt; ← تمدید · /revoke &lt;id&gt; ← گرفتن دسترسی و مسدود کردن\n"
    "/open on|off ← ثبت‌نام باز (هر کس خودکار ثبت می‌شه) · <code>/open trial 7</code> ← دوره‌ی آزمایشی (روز؛ ۰ = نامحدود)\n"
    "/stop · /run · /restart &lt;id&gt; ← مدیریت سلف هر کاربر · /log [id] ← لاگ\n"
    "/broadcast &lt;متن&gt; ← پیام به همه · /dump ← بکاپ کامل همه‌ی کاربرها (زیپ، ادمین)\n"
    "بروزرسانی: فایل زیپ رو با کپشن <code>/update</code> بفرست"
)
# ───────────── شروع: یه بات برای همه، بدون توکن ─────────────
START_PUBLIC = (
    "🐾 <b>سلف تلگرام — یه بات برای همه</b>\n\n"
    "لازم نیست بات بسازی، توکن بدی یا چیزی نصب کنی. فقط اکانتت رو وصل کن؛ "
    "سلف مخصوص خودت <b>خودکار روی سرور ساخته و اجرا می‌شه</b>.\n\n"
    "۱️⃣ شماره‌ات رو بده\n"
    "۲️⃣ کدی که تلگرام می‌فرسته رو وارد کن\n"
    "۳️⃣ اگه رمز دومرحله‌ای داری، اون رو بده\n\n"
    "بعدش از همین بات + مینی‌اپ کنترلش می‌کنی: بازی میویی (میو، ماهیگیری، یخچال، پیشی، خفاش، نجات)، "
    "مدیریت گروه، پشتیبان‌گیری و بقیه‌ی قابلیت‌ها.\n\n"
    "👇 برای شروع بزن:"
)
PUBLIC_HELP = (
    "❓ <b>راهنما</b>\n\n"
    "🚀 «ساخت سلف من» یا /connect ← شماره ← کد ← (رمز دومرحله‌ای) ← سلفت خودکار ساخته می‌شه.\n"
    "🔳 اگه نمی‌خوای کد بزنی: ورود با QR (از یه دستگاه دیگه) یا «ورود از صفحه‌ی وب».\n"
    "📱 بعد از ساخته شدن: /panel و /app (مینی‌اپ).\n\n"
    "هیچ توکن یا بات جداگانه‌ای لازم نیست."
)
FEATURES_PUBLIC = (
    "✨ <b>قابلیت‌های سلف تو</b>\n\n"
    "🐱 بازی میویی: میو، ماهیگیری، یخچال، پیشی (برداشت میو پوینت)، خفاش، نجات خودکار\n"
    "🛡 مدیریت گروه: نگهبان، قفل‌ها، فیلتر، عضویت اجباری، سکوت\n"
    "⏰ ساعت، تاریخ شمسی، منشی، پاسخ خودکار، آفلاین، ضد حذف و...\n"
    "💾 پشتیبان‌گیری و بازیابی کامل\n"
    "📱 مینی‌اپ + پنل دکمه‌ای برای کنترل از همین بات\n\n"
    "همه‌ش با یه بار وصل کردن اکانت 👇"
)
READY_TEXT = ("🟢 <b>سلفت ساخته شد و روشنه!</b>\n\n"
              "حالا توی هر چت (مثلاً چت بازی میویی) دستورهای نقطه‌ای رو بزن:\n"
              "<code>.میویی</code> · <code>.ماهیگیری</code> · <code>.یخچال</code> · <code>.پیشی</code>\n"
              "یا از دکمه‌های زیر کنترلش کن 👇")


def public_start_kb(uid=None) -> dict:
    rows = [[botpanel.btn("🚀 ساخت سلف من", "ob:go", "success")],
            [botpanel.btn("✨ قابلیت‌ها", "st:features", "primary"), botpanel.btn("❓ راهنما", "st:help", "primary")]]
    return {"inline_keyboard": rows}


def ready_kb(uid) -> dict:
    rows = [[botpanel.btn("⚙️ پنل", "m", "primary"), botpanel.btn("📊 وضعیت", "mg:status", "primary")]]
    url = app_base_url()
    if url:
        rows.insert(0, [{"text": "📱 باز کردن مینی‌اپ", "web_app": {"url": url}}])
    return {"inline_keyboard": rows}


async def send_start(bot, uid, cid):
    """/start برای همه: کاربری که سلف داره پنل می‌بینه، بقیه دکمه‌ی «ساخت سلف من»."""
    if is_allowed(uid) and has_session(uid):
        run = "روشنه 🟢" if is_running(uid) else "خاموشه 🔴"
        return await bot.send(cid, f"👋 خوش اومدی! سلفت {run}.\nپنل، وضعیت و مینی‌اپ پایینه 👇", ready_kb(uid))
    await bot.send(cid, START_PUBLIC, public_start_kb(uid))


# ───────────── ثبت‌نام باز: هر کس خودکار وارد می‌شه ─────────────
OPEN_DEFAULT = True
TRIAL_DEFAULT = 0
BOT_STATE = {"ok": None, "error": ""}  # وضعیت اتصال بات (برای تشخیص «توکن قبول نمی‌شه»)


def is_open() -> bool:
    return bool(load_reg().get("open", OPEN_DEFAULT))


def trial_days() -> int:
    return int(load_reg().get("trial_days", TRIAL_DEFAULT) or 0)


def is_banned(uid) -> bool:
    return str(uid) in (load_reg().get("banned") or [])


def set_open(value: bool):
    reg = load_reg()
    reg["open"] = bool(value)
    save_reg(reg)


def set_trial(days: int):
    reg = load_reg()
    reg["trial_days"] = max(0, int(days))
    save_reg(reg)


def ban_user(uid):
    reg = load_reg()
    if str(uid) not in (reg.get("banned") or []):
        reg.setdefault("banned", []).append(str(uid))
        save_reg(reg)


def unban_user(uid):
    reg = load_reg()
    if str(uid) in (reg.get("banned") or []):
        reg["banned"].remove(str(uid))
        save_reg(reg)


async def ensure_access(bot, msg) -> bool:
    """True = این کاربر می‌تونه ادامه بده. ثبت‌نام باز: کاربر جدید خودکار ثبت می‌شه (دوره‌ی آزمایشی اختیاری)؛
    بسته: درخواست برای ادمین می‌ره. اشتراک تموم‌شده: درخواست تمدید. مسدودشده: رد."""
    user, chat = msg["from"], msg["chat"]["id"]
    uid = user["id"]
    if is_allowed(uid):
        return True
    if is_banned(uid):
        await bot.send(chat, "⛔ دسترسی‌ت توسط ادمین بسته شده.")
        return False
    if get_entry(uid) is not None:  # قبلاً کاربر بوده و اشتراکش تموم شده
        await request_access(bot, msg)
        return False
    if is_open():
        name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
        allow_user(uid, name, trial_days())
        if ADMIN:
            try:
                un = f"@{user['username']}" if user.get("username") else "—"
                await bot.send(ADMIN, f"👤 کاربر جدید: {html.escape(name)} {html.escape(un)} <code>{uid}</code>")
            except Exception:  # noqa
                pass
        return True
    await request_access(bot, msg)
    return False


async def announce_ready(uid, chat):
    """بعد از ورود موفق: صبر می‌کنه تا سلف واقعاً بالا بیاد و خبر می‌ده (ساخت/اجرای خودکار)."""
    bot = _bot_ref.get("bot")
    if not bot:
        return
    for _ in range(45):  # حدود ۹۰ ثانیه
        await asyncio.sleep(2)
        inst = INSTANCES.get(uid)
        if inst and inst.failed:
            break
        st = read_status(uid)
        if st and time.time() - st.get("ts", 0) < 40:
            if st.get("authorized"):
                return await bot.send(chat, READY_TEXT, ready_kb(uid))
            break  # سلف بالا اومد ولی سشن معتبر نیست
    try:
        await bot.send(chat, "⚠️ سلفت هنوز آماده نشد. /status رو بزن؛ اگه مشکل موند /restart، و اگه باز هم نشد "
                             "/disconnect و دوباره /connect.")
    except Exception:  # noqa
        pass

CONSENT = (
    "⚠️ <b>قبل از وصل کردن اکانت بخون</b>\n\n"
    "• اکانتت روی سرور این هاب اجرا می‌شه و سشن ورودت اونجا ذخیره می‌شه؛ یعنی ادمین سرور از نظر فنی به اون دسترسی داره.\n"
    "• سلف بدون اجازه‌ی تو کاری نمی‌کنه، ولی هر قابلیتی که روشن کنی از اکانت خودت اجرا می‌شه و مسئولیتش با خودته.\n"
    "• هر وقت خواستی /disconnect بزن، یا از تلگرام ← Settings ← Devices نشستش رو ببند.\n\n"
    "اگه موافقی ادامه بده."
)


# ───────────── Bot API ─────────────
class Bot:
    def __init__(self, session):
        self.s = session

    async def api(self, method, **params):
        return await botpanel.call(self.s, TOKEN, method, **params)

    async def send(self, chat, text, kb=None):
        return await self.api("sendMessage", chat_id=chat, text=text, parse_mode="HTML",
                              reply_markup=kb, disable_web_page_preview=True)

    async def upload(self, method, params, field, filename, data):
        """ارسال فایل (multipart) برای sendPhoto / sendDocument / editMessageMedia."""
        form = aiohttp.FormData()
        for k, v in params.items():
            if v is not None:
                form.add_field(k, v if isinstance(v, str) else str(v))
        form.add_field(field, data, filename=filename)
        async with self.s.post(botpanel.API_URL.format(token=TOKEN, method=method), data=form) as r:
            res = await r.json(content_type=None)
        if not res.get("ok"):
            raise botpanel.BotError(res.get("description", "?"), res.get("error_code"))
        return res["result"]

    async def edit(self, chat, mid, text, kb=None):
        try:
            await self.api("editMessageText", chat_id=chat, message_id=mid, text=text, parse_mode="HTML",
                           reply_markup=kb, disable_web_page_preview=True)
        except botpanel.BotError as e:
            if "not modified" not in str(e):
                raise

    async def delete(self, chat, mid):
        try:
            await self.api("deleteMessage", chat_id=chat, message_id=mid)
        except Exception:  # noqa
            pass

    async def answer(self, qid, text=None):
        try:
            await self.api("answerCallbackQuery", callback_query_id=qid, text=text)
        except Exception:  # noqa
            pass


async def notify_failed(uid):
    BOT = _bot_ref.get("bot")
    if BOT:
        try:
            await BOT.send(uid, "⚠️ سلفت چند بار پشت‌سرهم کرش کرد و متوقف شد. /restart رو امتحان کن؛ اگه ادامه داشت به ادمین خبر بده.")
        except Exception:  # noqa
            pass


_bot_ref = {}
ACCESS_KB = lambda uid: {"inline_keyboard": [
    [botpanel.btn("✅ ۳۰ روز", f"ok:{uid}:30", "success"), botpanel.btn("✅ ۷ روز", f"ok:{uid}:7", "success"),
     botpanel.btn("♾ نامحدود", f"ok:{uid}:0", "primary")],
    [botpanel.btn("❌ رد", f"no:{uid}", "danger")]]}


# ───────────── ورود اکانت ─────────────
def make_client():
    return TelegramClient(StringSession(), API_ID, API_HASH, **meow.proxy_kwargs(os.getenv("PROXY", "")))


async def cleanup_login(uid):
    st = LOGIN.pop(uid, None)
    t = st.get("task") if st else None
    if t and t is not asyncio.current_task():
        t.cancel()
    if st and st.get("mid") and st.get("step") in ("qr", "pw") and _bot_ref.get("bot") and st.get("task"):
        await _bot_ref["bot"].delete(st["chat"], st["mid"])
    if st and st.get("client"):
        try:
            await st["client"].disconnect()
        except Exception:  # noqa
            pass


async def purge_logins():
    now = time.time()
    for uid in [u for u, st in LOGIN.items() if now - st["ts"] > LOGIN_TTL]:
        await cleanup_login(uid)


async def begin_login(bot, uid, chat):
    if has_session(uid):
        return await bot.send(chat, "✅ قبلاً اکانتت وصل شده. وضعیت: /status\nبرای وصل کردن اکانت دیگه اول /disconnect بزن.")
    if not (API_ID and API_HASH):
        return await bot.send(chat, "❌ ادمین هنوز API_ID/API_HASH رو تنظیم نکرده.")
    if uid != ADMIN and len(connected_users()) >= MAX_USERS:
        return await bot.send(chat, "❌ ظرفیت هاب پره؛ به ادمین خبر بده.")
    await cleanup_login(uid)
    await bot.send(chat, CONSENT, {"inline_keyboard": [[botpanel.btn("✅ قبول دارم، ادامه", "go", "success")]]})


METHOD_KB = {"inline_keyboard": [[botpanel.btn("🔳 با QR (بدون کد)", "qr", "primary"), botpanel.btn("📱 با شماره", "ph", "success")]]}


def method_keyboard(uid) -> dict:
    """روش‌های ورود؛ اگه دامنه‌ی عمومی هست، «ورود از صفحه‌ی وب» (لینک یک‌بارمصرف) هم بالاش میاد."""
    rows = [list(r) for r in METHOD_KB["inline_keyboard"]]
    url = web_login_url(uid)
    if url:
        rows.insert(0, [{"text": "🌐 ورود از صفحه‌ی وب (پیشنهادی)", "url": url}])
    return {"inline_keyboard": rows}


async def ask_phone(bot, uid, chat):
    LOGIN[uid] = {"step": "phone", "ts": time.time(), "chat": chat, "client": None}
    await bot.send(chat, "📱 شماره‌ی اکانتت رو بفرست (مثلاً <code>+989121234567</code> یا <code>09121234567</code>).\nلغو: /cancel")


def parse_phone(text):
    return core.normalize_phone(text)


def code_prompt(sent) -> tuple:
    """(متن، کیبورد) بعد از ارسال کد: راه ارسال + هشدار خط تیره + دکمه‌ی روش بعدی."""
    how, nxt = core.sent_code_info(sent)
    text = (f"📩 کد فرستاده شد: <b>{how}</b>\n\n"
            "⚠️ <b>کد رو با فاصله یا خط تیره بنویس</b>، مثلاً <code>1-2-3-4-5</code>. "
            "اگه پشت‌سرهم بفرستی تلگرام کد رو باطل می‌کنه!")
    hint = core.api_hint()
    if hint:
        text += "\n\n" + html.escape(hint)
    kb = {"inline_keyboard": [[botpanel.btn(nxt, "rs", "primary")]]} if nxt else None
    return text, kb


def login_error_text(e) -> str:
    if isinstance(e, PhoneNumberFloodError):
        return "⏳ این شماره زیاد درخواست کد داده؛ چند ساعت دیگه امتحان کن."
    if isinstance(e, SendCodeUnavailableError):
        return "❌ همه‌ی راه‌های ارسال کد (اپ، پیامک، تماس) برای این شماره استفاده شد؛ یه مدت بعد دوباره امتحان کن."
    if isinstance(e, (ConnectionError, OSError, asyncio.TimeoutError)):
        return "❌ اتصال به تلگرام برقرار نشد (شبکه یا پروکسی). چند لحظه بعد دوباره امتحان کن."
    return f"❌ خطا: {type(e).__name__}: {html.escape(str(e))[:150]}"


async def handle_login(bot, msg):
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    st = LOGIN[uid]
    st["ts"] = time.time()
    text = (msg.get("text") or "").strip()
    await bot.delete(chat, msg["message_id"])  # شماره/کد/رمز نباید توی چت بمونه
    step = st["step"]
    if step == "qr":
        return await bot.send(chat, "🔳 QR رو توی یه دستگاه دیگه اسکن کن (یا /cancel).")
    try:
        if step == "phone":
            phone = parse_phone(text)
            if not phone:
                return await bot.send(chat, "❌ شماره معتبر نیست. مثال: <code>+989121234567</code>")
            client = make_client()
            await client.connect()
            st["client"] = client
            sent = await client.send_code_request(phone)
            st.update(phone=phone, hash=sent.phone_code_hash, step="code")
            text, kb = code_prompt(sent)
            return await bot.send(chat, text, kb)
        if step == "code":
            code = re.sub(r"\D", "", num(text))
            if not code:
                return await bot.send(chat, "❌ فقط عدد کد رو بفرست (مثلاً <code>1-2-3-4-5</code>)")
            try:
                await st["client"].sign_in(phone=st["phone"], code=code, phone_code_hash=st["hash"])
            except SessionPasswordNeededError:
                st["step"] = "pw"
                return await bot.send(chat, "🔐 رمز تأیید دومرحله‌ای (2FA) رو بفرست. پیامت بعد از خوندن پاک می‌شه.")
            return await finish_login(bot, uid, chat)
        if step == "pw":
            await st["client"].sign_in(password=text)
            return await finish_login(bot, uid, chat)
    except PhoneNumberInvalidError:
        await cleanup_login(uid)
        await bot.send(chat, "❌ شماره نامعتبره. دوباره /connect")
    except PhoneNumberBannedError:
        await cleanup_login(uid)
        await bot.send(chat, "❌ این شماره توی تلگرام بن شده.")
    except PhoneCodeInvalidError:
        await bot.send(chat, "❌ کد اشتباهه. دوباره بفرست (با خط تیره).")
    except PhoneCodeExpiredError:
        await cleanup_login(uid)
        await bot.send(chat, "⌛ کد منقضی شد (یا تلگرام چون پشت‌سرهم نوشته بودی باطلش کرد). دوباره /connect و این بار با خط تیره بنویس.")
    except PasswordHashInvalidError:
        await bot.send(chat, "❌ رمز اشتباهه. دوباره بفرست.")
    except FloodWaitError as e:
        await cleanup_login(uid)
        await bot.send(chat, f"⏳ تلگرام موقتاً محدود کرد؛ {fmt_dur(e.seconds)} دیگه امتحان کن.")
    except ApiIdInvalidError:
        await cleanup_login(uid)
        await bot.send(chat, "❌ API_ID/API_HASH هاب نامعتبره؛ به ادمین خبر بده.")
    except Exception as e:  # noqa
        log.warning("[u%s] login error at step %s: %r", uid, step, e)
        msg = login_error_text(e)
        if step == "phone":  # بدون این، کاربر هیچ‌چیز نمی‌دید و فکر می‌کرد «کد نمیاد»
            await cleanup_login(uid)
            hint = core.api_hint()
            msg += "\nدوباره /connect" + (f"\n\n{html.escape(hint)}" if hint else "")
        await bot.send(chat, msg)


async def finish_login(bot, uid, chat):
    st = LOGIN[uid]
    client = st["client"]
    me = await client.get_me()
    session = client.session.save()
    await cleanup_login(uid)
    os.makedirs(udir(uid), exist_ok=True)
    with open(upath(uid, "session.txt"), "w") as f:
        f.write(session)
    write_json(upath(uid, "api.json"), {"id": API_ID, "hash": API_HASH})
    try:
        os.remove(stopped_marker(uid))
    except OSError:
        pass
    get_instance(uid).start()
    name = " ".join(x for x in (me.first_name, me.last_name) if x) or "بدون نام"
    try:  # برای هدر مینی‌اپ (اسم اکانت)
        write_json(upath(uid, "profile.json"),
                   {"id": me.id, "name": name, "username": getattr(me, "username", None)})
    except Exception:  # noqa
        pass
    await bot.send(chat, f"✅ وصل شد: <b>{html.escape(name)}</b>\n\n"
                         "⏳ دارم سلفت رو می‌سازم و راه می‌اندازم (حدود ۱۰ تا ۳۰ ثانیه)؛ آماده شد همین‌جا خبرت می‌کنم.")
    asyncio.create_task(announce_ready(uid, chat))


# ───────────── دستورها ─────────────
def need_connected(uid) -> bool:
    return has_session(uid)


async def cmd_panel(bot, uid, chat, arg):
    if not has_session(uid):
        return await bot.send(chat, "🔌 اول اکانتت رو وصل کن: /connect")
    await bot.send(chat, main_text(uid), main_keyboard(uid))


async def cmd_status(bot, uid, chat, arg):
    t = tgt(uid, arg) if arg.strip().isdigit() else uid
    if uid != ADMIN and t != uid:
        t = uid
    kb = {"inline_keyboard": [
        [botpanel.btn("🔄 ریستارت", "mg:restart", "primary"),
         botpanel.btn("🔴 خاموش", "mg:stop", "danger") if is_running(t) else botpanel.btn("🟢 روشن", "mg:run", "success")],
        [botpanel.btn("🎛 پنل", "m", "primary"), botpanel.btn("💾 بکاپ", "mg:backup", "primary")],
    ]}
    await bot.send(chat, status_text(t), kb)


async def cmd_cmd(bot, uid, chat, arg):
    inst = INSTANCES.get(uid)
    parts = arg.split(maxsplit=1)
    if len(parts) < 2:
        return await bot.send(chat, "مثال: <code>/cmd me .وضعیت چت</code>\nهدف: <code>me</code> (Saved Messages)، <code>@username</code> یا آیدی عددی چت.")
    if not (inst and inst.running):
        return await bot.send(chat, "🔴 سلفت در حال اجرا نیست (/run)")
    target, text = parts
    if target.lower() == "me":
        target = "me"
    elif not (target.startswith("@") or target.lstrip("-").isdigit()):
        return await bot.send(chat, "❌ هدف باید <code>me</code> ، <code>@username</code> یا آیدی عددی باشه")
    ctl_send(uid, op="run", chat=target, text=text)
    await bot.send(chat, f"✅ فرستاده شد به <code>{html.escape(target)}</code>: <code>{html.escape(text[:200])}</code>")


def tgt(uid, arg):
    """ادمین می‌تونه آیدی کاربر رو بده؛ بقیه فقط خودشون."""
    return int(arg.strip()) if uid == ADMIN and arg.strip().isdigit() else uid


def revive(target):
    """بعد از تأیید/تمدید: اگه کاربر اکانت وصل داره و دستی متوقف نکرده، سلفش دوباره بالا بیاد."""
    if has_session(target) and is_allowed(target) and not os.path.exists(stopped_marker(target)):
        inst = get_instance(target)
        if not inst.running:
            inst.start()


async def cmd_stop(bot, uid, chat, arg):
    t = tgt(uid, arg)
    if not has_session(t):
        return await bot.send(chat, "🔌 اول /connect" if t == uid else "این کاربر اکانتی وصل نکرده")
    await get_instance(t).stop()
    open(stopped_marker(t), "w").close()
    await bot.send(chat, f"🔴 سلف{'' if t == uid else ' ' + str(t)} متوقف شد. دوباره: /run" + ("" if t == uid else f" {t}"))


async def cmd_run(bot, uid, chat, arg):
    t = tgt(uid, arg)
    if not has_session(t):
        return await bot.send(chat, "🔌 اول /connect" if t == uid else "این کاربر اکانتی وصل نکرده")
    if not is_allowed(t):
        return await bot.send(chat, "⌛ اشتراک منقضی شده؛ اول تمدید (/extend)")
    try:
        os.remove(stopped_marker(t))
    except OSError:
        pass
    get_instance(t).start()
    await bot.send(chat, "🟢 سلف داره بالا میاد...")


async def cmd_restart(bot, uid, chat, arg):
    t = tgt(uid, arg)
    if not has_session(t):
        return await bot.send(chat, "🔌 اول /connect" if t == uid else "این کاربر اکانتی وصل نکرده")
    if not is_allowed(t):
        return await bot.send(chat, "⌛ اشتراک منقضی شده؛ اول تمدید (/extend)")
    inst = get_instance(t)
    await bot.send(chat, "🔄 دارم ریستارت می‌کنم...")
    await inst.stop()
    try:
        os.remove(stopped_marker(t))
    except OSError:
        pass
    inst.start()


async def cmd_disconnect(bot, uid, chat, arg):
    if not has_session(uid):
        return await bot.send(chat, "هیچ اکانتی وصل نیست.")
    await bot.send(chat, "⚠️ با این کار سلفت متوقف می‌شه، از تلگرام خارج می‌شی (نشست بسته می‌شه) و همه‌ی تنظیماتت پاک می‌شه.",
                   {"inline_keyboard": [[botpanel.btn("🗑 بله، حذف کن", "dc", "danger"), botpanel.btn("لغو", "x", "primary")]]})


async def do_disconnect(uid):
    inst = INSTANCES.pop(uid, None)
    if inst:
        await inst.stop()
    sess = ""
    try:
        sess = open(upath(uid, "session.txt")).read().strip()
    except OSError:
        pass
    if sess and API_ID:
        try:
            c = TelegramClient(StringSession(sess), API_ID, API_HASH, **meow.proxy_kwargs(os.getenv("PROXY", "")))
            await c.connect()
            await c.log_out()
        except Exception as e:  # noqa
            log.warning("[u%s] logout failed: %r", uid, e)
    shutil.rmtree(udir(uid), ignore_errors=True)


async def cmd_cancel(bot, uid, chat, arg):
    if uid in LOGIN:
        await cleanup_login(uid)
        return await bot.send(chat, "لغو شد.")
    await bot.send(chat, "چیزی برای لغو نیست.")


# ادمین
async def cmd_users(bot, uid, chat, arg):
    reg = load_reg()
    ids = sorted(set([ADMIN] + [int(k) for k in reg["allowed"]] + connected_users()))
    rows, total = [], 0.0
    for u in ids:
        inst = INSTANCES.get(u)
        state_ = "🟢" if inst and inst.running else ("⚠️" if inst and inst.failed else ("🔴" if has_session(u) else "⚪️"))
        mem = inst.rss() if inst else None
        total += mem or 0
        name = reg["allowed"].get(str(u), {}).get("name", "ادمین" if u == ADMIN else "")
        rows.append(f"{state_} <code>{u}</code> {html.escape(name or '')} · {sub_text(u)}" + (f" · {mem:.0f}MB" if mem else ""))
    await bot.send(chat, f"👥 کاربرها ({len(connected_users())}/{MAX_USERS} وصل" + (f" · رم کل {total:.0f}MB" if total else "") + ")\n\n" +
                   "\n".join(rows) + "\n\n🟢 در حال اجرا · 🔴 متوقف · ⚪️ اکانت وصل نکرده")


async def cmd_allow(bot, uid, chat, arg):
    parts = arg.split(maxsplit=2)
    if not parts or not parts[0].isdigit():
        return await bot.send(chat, "مثال: <code>/allow 123456789 30 علی</code> (۳۰ روز؛ بدون عدد یا ۰ = نامحدود)")
    target, days, name = int(parts[0]), 0, ""
    rest = parts[1:]
    if rest and rest[0].isdigit():
        days, name = int(rest[0]), (rest[1] if len(rest) > 1 else "")
    elif rest:
        name = " ".join(rest)
    allow_user(target, name, days)
    revive(target)
    dur = f"{days} روز" if days else "نامحدود"
    await bot.send(chat, f"✅ دسترسی <code>{target}</code> داده شد ({dur})")
    try:
        await bot.send(target, f"✅ ادمین دسترسی‌ات رو تأیید کرد ({dur}). /connect برای وصل کردن اکانت یا /help")
    except Exception:  # noqa
        pass


async def cmd_extend(bot, uid, chat, arg):
    parts = arg.split()
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()) or int(parts[1]) <= 0:
        return await bot.send(chat, "مثال: <code>/extend 123456789 30</code> (۳۰ روز اضافه)")
    target, days = int(parts[0]), int(parts[1])
    if not extend_user(target, days):
        return await bot.send(chat, "❌ این کاربر توی لیست نیست (اول /allow)")
    revive(target)
    await bot.send(chat, f"✅ اشتراک <code>{target}</code> {days} روز تمدید شد ({sub_text(target)})")
    try:
        await bot.send(target, f"✅ اشتراکت {days} روز تمدید شد ({sub_text(target)}).")
    except Exception:  # noqa
        pass


async def cmd_revoke(bot, uid, chat, arg):
    if not arg.strip().isdigit():
        return await bot.send(chat, "مثال: <code>/revoke 123456789</code>")
    target = int(arg.strip())
    if target == ADMIN:
        return await bot.send(chat, "❌ ادمین رو نمی‌شه حذف کرد")
    reg = load_reg()
    reg["allowed"].pop(str(target), None)
    save_reg(reg)
    ban_user(target)  # توی ثبت‌نام باز، کاربرِ گرفته‌شده‌ی دسترسی خودکار دوباره ثبت نشه (/allow آزادش می‌کنه)
    inst = INSTANCES.get(target)
    if inst:
        await inst.stop()
    await bot.send(chat, f"✅ دسترسی <code>{target}</code> گرفته شد و سلفش متوقف شد (اطلاعاتش می‌مونه؛ حذف کامل: خودش /disconnect بزنه)")


async def cmd_open(bot, uid, chat, arg):
    """/open on|off ← ثبت‌نام باز · /open trial <روز> ← دوره‌ی آزمایشی کاربرهای جدید (۰ = نامحدود)."""
    parts = arg.lower().split()
    if parts and parts[0] in ("on", "روشن", "1"):
        set_open(True)
    elif parts and parts[0] in ("off", "خاموش", "0"):
        set_open(False)
    elif len(parts) == 2 and parts[0] in ("trial", "آزمایشی") and parts[1].isdigit():
        set_trial(int(parts[1]))
    elif parts:
        return await bot.send(chat, "مثال: <code>/open on</code> · <code>/open off</code> · <code>/open trial 7</code>")
    t = trial_days()
    await bot.send(chat, f"🚪 ثبت‌نام باز: <b>{'روشن ✅ (هر کس خودکار ثبت می‌شه)' if is_open() else 'خاموش 🔒 (فقط با تأیید تو)'}</b>\n"
                         f"🎁 دوره‌ی آزمایشی: <b>{str(t) + ' روز' if t else 'نامحدود'}</b>\n"
                         f"👥 ظرفیت: {len(connected_users())}/{MAX_USERS}")


async def cmd_broadcast(bot, uid, chat, arg):
    if not arg.strip():
        return await bot.send(chat, "مثال: <code>/broadcast ساعت ۱۲ سرور ریستارت می‌شه</code>")
    targets = ({int(k) for k in load_reg()["allowed"]} | set(connected_users())) - {ADMIN}
    ok = bad = 0
    for t in sorted(targets):
        try:
            await bot.send(t, "📢 <b>پیام ادمین</b>\n\n" + html.escape(arg.strip()))
            ok += 1
        except Exception:  # noqa
            bad += 1
        await asyncio.sleep(0.05)
    await bot.send(chat, f"📢 ارسال شد: {ok} موفق" + (f" · {bad} ناموفق (بات رو بلاک کرده‌ن)" if bad else ""))


async def cmd_log(bot, uid, chat, arg):
    target = int(arg.strip()) if arg.strip().isdigit() else uid
    inst = INSTANCES.get(target)
    lines = list(inst.logs)[-25:] if inst else []
    body = html.escape("\n".join(lines)[-3500:]) or "—"
    await bot.send(chat, f"📜 لاگ <code>{target}</code>:\n<pre>{body}</pre>")


async def cmd_backup(bot, uid, chat, arg):
    data = sanitized_settings(uid)
    if data is None:
        return await bot.send(chat, "🔌 هنوز تنظیماتی نداری (اول /connect)")
    raw = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
    name = f"self-backup-{datetime.datetime.now():%Y%m%d}.json"
    await bot.upload("sendDocument", {"chat_id": chat, "caption": "💾 پشتیبان تنظیمات سلفت (بدون سشن، بدون توکن و پروکسی).\nبرگردوندن: همین فایل رو با کپشن /restore بفرست.\nبکاپ کامل (با سشن): /backup_full"},
                     "document", name, raw)


async def cmd_backup_full(bot, uid, chat, arg):
    """بکاپ کامل: settings.json + session.txt + api.json توی یه زیپ. خیلی حساسه — جایی فوروارد نکن."""
    if not has_session(uid):
        return await bot.send(chat, "🔌 هنوز اکانتی وصل نکردی (اول /connect)")
    make_backup(uid)  # یه نسخه‌ی امن هم توی بکاپ‌های خودکار بمونه
    tmp = tempfile.mkdtemp(prefix="fullbak_")
    try:
        zpath = os.path.join(tmp, f"self-full-{uid}-{datetime.datetime.now():%Y%m%d-%H%M}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ("settings.json", "session.txt", "api.json"):
                p = upath(uid, name)
                if os.path.isfile(p):
                    z.write(p, name)
            z.writestr("README.txt", "بکاپ کامل سلف هاب\nبرگردوندن: همین زیپ رو با کپشن /restore بفرست.\n⚠️ حاوی سشن ورود تلگرامه؛ به هیچ‌کس نده و بعد از بازیابی از چت پاکش کن.")
        with open(zpath, "rb") as f:
            raw = f.read()
        await bot.upload("sendDocument", {"chat_id": chat,
                          "caption": "💾 <b>بکاپ کامل</b> (تنظیمات + سشن).\n⚠️ مثل رمزت ازش مراقبت کن؛ بعد از دانلود از چت پاکش کن.\nبرگردوندن: همین فایل رو با کپشن /restore بفرست."},
                         "document", os.path.basename(zpath), raw)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def cmd_dump(bot, uid, chat, arg):
    """ادمین: بکاپ کامل همه‌ی کاربرها (users.json + بکاپ امن همه، بدون سشن)."""
    tmp = tempfile.mkdtemp(prefix="hubdump_")
    try:
        zpath = os.path.join(tmp, f"hub-dump-{datetime.datetime.now():%Y%m%d-%H%M}.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            reg_p = os.path.join(DATA, "users.json")
            if os.path.isfile(reg_p):
                z.write(reg_p, "users.json")
            for name in sorted(os.listdir(DATA)):
                if not name.isdigit():
                    continue
                for fn in ("settings.json", "api.json"):
                    p = os.path.join(DATA, name, fn)
                    if os.path.isfile(p):
                        if fn == "settings.json":
                            try:
                                d = read_json(p, {})
                                cfg = {k: v for k, v in (d.get("cfg") or {}).items() if k not in ("bot_token", "proxy")}
                                z.writestr(f"{name}/{fn}", json.dumps({"features": d.get("features") or {}, "cfg": cfg}, ensure_ascii=False, indent=1))
                                continue
                            except Exception:  # noqa
                                pass
                        z.write(p, f"{name}/{fn}")
                lb = latest_backup(int(name)) if name.isdigit() else None
                if lb and os.path.isfile(lb):
                    z.write(lb, f"{name}/auto-backup.json")
        with open(zpath, "rb") as f:
            raw = f.read()
        await bot.upload("sendDocument", {"chat_id": chat, "caption": f"💾 بکاپ کل هاب (بدون سشن‌ها، {len(raw)//1024}KB). بازیابی هر کاربر جدا با /restore انجام می‌شه."},
                         "document", os.path.basename(zpath), raw)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


















async def cmd_app(bot, uid, chat, arg):
    url = app_base_url()
    app_line = f"👇 بازش کن:\n{html.escape(url)}" if url else "⚠️ ادمین هنوز <code>HUB_DOMAIN</code> رو ست نکرده؛ فعلاً از /panel استفاده کن."
    kb = {"inline_keyboard": [[{"text": "📱 باز کردن مینی‌اپ", "web_app": {"url": url}}]]} if url else None
    text = MINIAPP_HELP.format(app_line=app_line, app_url=html.escape(url or "https://YOUR-DOMAIN.up.railway.app/app"))
    await bot.send(chat, text, kb)


async def cmd_restore(bot, uid, chat, arg):
    if arg.strip().lower() == "last":
        p = latest_backup(uid)
        if not p:
            return await bot.send(chat, "❌ بکاپ خودکاری برات ثبت نشده")
        return await bot.send(chat, "✅ " + await do_restore(uid, read_json(p, None)))
    await bot.send(chat, "برای برگردوندن: فایل پشتیبان (.json یا زیپ بکاپ کامل) رو با کپشن <code>/restore</code> بفرست، یا <code>/restore last</code> برای آخرین بکاپ خودکار.")


async def download_telegram_file(bot, file_id: str) -> bytes:
    info = await bot.api("getFile", file_id=file_id)
    async with bot.s.get(f"https://api.telegram.org/file/bot{TOKEN}/{info['file_path']}") as r:
        return await r.read()


async def restore_from_doc(bot, uid, chat, doc):
    fname = str(doc.get("file_name", "")).lower()
    if doc.get("file_size", 0) > 5_000_000 or not (fname.endswith(".json") or fname.endswith(".zip")):
        return await bot.send(chat, "❌ فقط فایل .json یا .zip بکاپ کامل (کمتر از ۵ مگابایت)")
    raw = await download_telegram_file(bot, doc["file_id"])
    # زیپ بکاپ کامل
    if fname.endswith(".zip"):
        try:
            msg = await do_restore_zip(uid, raw)
        except ValueError as e:
            return await bot.send(chat, f"❌ فایل معتبر نیست: {html.escape(str(e))[:200]}")
        return await bot.send(chat, "✅ " + msg + "\n🔄 سلف داره با تنظیمات جدید بالا میاد...")
    try:
        msg = await do_restore(uid, json.loads(raw.decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as e:
        return await bot.send(chat, f"❌ فایل معتبر نیست: {html.escape(str(e))[:200]}")
    await bot.send(chat, "✅ " + msg)


async def do_restore_zip(uid, raw: bytes) -> str:
    """بازیابی از زیپ بکاپ کامل (settings.json حتماً، session.txt/api.json اگه باشن)."""
    tmp = tempfile.mkdtemp(prefix="restore_")
    try:
        zpath = os.path.join(tmp, "up.zip")
        with open(zpath, "wb") as f:
            f.write(raw)
        if not zipfile.is_zipfile(zpath):
            raise ValueError("فایل زیپ معتبر نیست")
        with zipfile.ZipFile(zpath) as z:
            names = set(z.namelist())
            if "settings.json" not in names:
                raise ValueError("توی زیپ settings.json پیدا نشد")
            try:
                obj = json.loads(z.read("settings.json").decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ValueError("settings.json داخل زیپ خرابه")
            feats, cfg = validate_backup(obj)
            inst = INSTANCES.get(uid)
            was_running = bool(inst and inst.running)
            if inst:
                await inst.stop()
            make_backup(uid)
            write_json(upath(uid, "settings.json"), {"features": feats, "cfg": cfg})
            restored = ["تنظیمات"]
            if "session.txt" in names:
                sess = z.read("session.txt").decode("utf-8", "ignore").strip()
                if len(sess) > 50:
                    with open(upath(uid, "session.txt"), "w") as f:
                        f.write(sess)
                    restored.append("سشن")
            if "api.json" in names:
                try:
                    api_obj = json.loads(z.read("api.json").decode("utf-8"))
                    if api_obj.get("id") and api_obj.get("hash"):
                        write_json(upath(uid, "api.json"), {"id": int(api_obj["id"]), "hash": str(api_obj["hash"])})
                        restored.append("API")
                except (ValueError, KeyError):
                    pass
            try:
                os.remove(stopped_marker(uid))
            except OSError:
                pass
            if (was_running or has_session(uid)) and is_allowed(uid):
                get_instance(uid).start()
            return f"بازیابی کامل انجام شد ({' + '.join(restored)}: {len(feats)} قابلیت)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def do_update(bot, uid, chat, doc):
    name = doc.get("file_name", "")
    if not name.lower().endswith((".zip", ".py")):
        return await bot.send(chat, "❌ فقط .zip یا .py")
    if doc.get("file_size", 0) > updater.MAX_ZIP:
        return await bot.send(chat, "❌ فایل بیشتر از ۸ مگابایته")
    await bot.send(chat, "⏳ دارم فایل رو بررسی می‌کنم...")
    info = await bot.api("getFile", file_id=doc["file_id"])
    import tempfile
    tmp = tempfile.mkdtemp(prefix="hubupd_")
    try:
        path = os.path.join(tmp, "upload.bin")
        async with bot.s.get(f"https://api.telegram.org/file/bot{TOKEN}/{info['file_path']}") as r:
            with open(path, "wb") as f:
                f.write(await r.read())
        ok, text = await updater.apply(path, name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not ok:
        return await bot.send(chat, "❌ بروزرسانی انجام نشد (هیچ تغییری اعمال نشد)\n" + html.escape(text))
    await bot.send(chat, html.escape(text) + "\n🔄 هاب و همه‌ی سلف‌ها دارن ریستارت می‌شن...")
    await stop_all()  # قبل از exec همه‌ی سلف‌ها بسته بشن تا سشن دوبار وصل نشه
    updater.restart()


# ───────────── بکاپ ─────────────
def sanitized_settings(uid):
    """تنظیمات سلف بدون چیزهای حساس (توکن بات و پروکسی)."""
    data = read_json(upath(uid, "settings.json"), None)
    if not isinstance(data, dict):
        return None
    cfg = {k: v for k, v in (data.get("cfg") or {}).items() if k not in ("bot_token", "proxy")}
    return {"features": data.get("features") or {}, "cfg": cfg}


def backup_dir(uid):
    return os.path.join(DATA, "backups", str(uid))


def make_backup(uid):
    data = sanitized_settings(uid)
    if data is None:
        return None
    d = backup_dir(uid)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
    write_json(path, data)
    for old in sorted(os.listdir(d))[:-BACKUP_KEEP]:
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    return path


def latest_backup(uid):
    d = backup_dir(uid)
    try:
        files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    except OSError:
        return None
    return os.path.join(d, files[-1]) if files else None


def validate_backup(obj):
    """(features, cfg) تمیز‌شده یا ValueError."""
    if not isinstance(obj, dict) or not isinstance(obj.get("features"), dict) or not isinstance(obj.get("cfg"), dict):
        raise ValueError("ساختار فایل پشتیبان درست نیست (باید features و cfg داشته باشه)")
    feats = {k: bool(v) for k, v in obj["features"].items() if k in DEFAULT_FLAGS and k not in HIDDEN}
    cfg = {k: v for k, v in obj["cfg"].items() if k not in ("bot_token", "proxy")}
    return feats, cfg


async def do_restore(uid, obj) -> str:
    feats, cfg = validate_backup(obj)
    inst = INSTANCES.get(uid)
    was_running = bool(inst and inst.running)
    if inst:
        await inst.stop()
    make_backup(uid)  # نسخه‌ی فعلی قبل از جایگزینی
    write_json(upath(uid, "settings.json"), {"features": feats, "cfg": cfg})
    if has_session(uid) and (was_running or not os.path.exists(stopped_marker(uid))) and is_allowed(uid):
        get_instance(uid).start()
    return f"{len(feats)} قابلیت و {len(cfg)} تنظیم برگشت"


async def backup_all():
    for uid in connected_users():
        try:
            make_backup(uid)
        except Exception as e:  # noqa
            log.warning("[u%s] backup failed: %r", uid, e)


# ───────────── انقضای اشتراک ─────────────
async def check_expiry(bot):
    reg = load_reg()
    now = time.time()
    changed = False
    for k, e in reg["allowed"].items():
        exp = e.get("expires", 0)
        if not exp:
            continue
        uid, left = int(k), exp - now
        try:
            if left <= 0:
                if not e.get("expired"):
                    e["expired"], changed = True, True
                    inst = INSTANCES.get(uid)
                    if inst:
                        await inst.stop()  # is_allowed خودش جلوی بالا اومدن دوباره رو می‌گیره
                    await bot.send(uid, "⌛ اشتراکت تموم شد و سلفت متوقف شد (اطلاعاتت می‌مونه). برای تمدید به ادمین پیام بده و /start بزن.")
                    await bot.send(ADMIN, f"⌛ اشتراک <code>{uid}</code> {html.escape(e.get('name', ''))} تموم شد. تمدید: <code>/extend {uid} 30</code>")
            elif left <= DAY and not e.get("warn1"):
                e["warn1"] = e["warn3"] = True
                changed = True
                await bot.send(uid, "⏰ کمتر از ۱ روز از اشتراکت مونده. برای تمدید به ادمین پیام بده.")
            elif left <= 3 * DAY and not e.get("warn3"):
                e["warn3"], changed = True, True
                await bot.send(uid, f"⏰ {-(-int(left) // DAY)} روز از اشتراکت مونده. برای تمدید به ادمین پیام بده.")
        except Exception as ex:  # noqa
            log.warning("expiry notify failed for %s: %r", uid, ex)
    if changed:
        save_reg(reg)


# ───────────── نگهبان رم و انتقال هشدارها ─────────────
_rss_alert = {}


async def watchdog(bot):
    if not MAX_RSS_MB:
        return
    for uid, inst in list(INSTANCES.items()):
        m = inst.rss()
        if m and m > MAX_RSS_MB:
            log.warning("[u%s] RSS %.0fMB > %sMB → restart", uid, m, MAX_RSS_MB)
            await inst.stop()
            inst.start()
            if time.time() - _rss_alert.get(uid, 0) > 1800:
                _rss_alert[uid] = time.time()
                for target in {uid, ADMIN}:
                    try:
                        await bot.send(target, f"🧠 سلف <code>{uid}</code> بیش از حد رم مصرف کرد ({m:.0f}MB > {MAX_RSS_MB}MB) و ریستارت شد.")
                    except Exception:  # noqa
                        pass


async def relay_alerts(bot):
    """هشدارهایی که سلف‌ها توی alerts.jsonl نوشتن رو با بات برای صاحبشون می‌فرسته."""
    for uid in list(INSTANCES):
        p = upath(uid, "alerts.jsonl")
        if not os.path.exists(p):
            continue
        work = p + ".work"
        try:
            os.replace(p, work)
        except OSError:
            continue
        texts = []
        try:
            with open(work, encoding="utf-8") as f:
                for line in f:
                    try:
                        texts.append(json.loads(line)["text"])
                    except (ValueError, KeyError):
                        pass
        finally:
            try:
                os.remove(work)
            except OSError:
                pass
        if texts:
            extra = f"\n\n… و {len(texts) - 8} هشدار دیگه" if len(texts) > 8 else ""
            try:
                await bot.send(uid, "\n\n".join(texts[:8]) + extra)
            except Exception as e:  # noqa
                log.warning("[u%s] alert relay failed: %r", uid, e)


async def maintenance():
    n = 0
    while True:
        await asyncio.sleep(5)
        n += 1
        bot = _bot_ref.get("bot")
        if not bot:
            continue
        try:
            await relay_alerts(bot)
            if n % 12 == 0:
                await watchdog(bot)
            if n % 120 == 0:
                await check_expiry(bot)
            if n % max(1, int(BACKUP_HOURS * 3600 / 5)) == 60:  # اولین بکاپ ~۵ دقیقه بعد از شروع
                await backup_all()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa
            log.warning("hub maintenance: %r", e)


# ───────────── ورود با QR ─────────────
QR_CAPTION = ("🔳 <b>ورود با QR</b>\n\n"
              "توی یه دستگاه دیگه‌ی همین اکانت: تلگرام ← Settings ← Devices ← <b>Link Desktop Device</b> ← این QR رو اسکن کن.\n"
              "هر ۳۰ ثانیه خودکار نو می‌شه. لغو: /cancel")


def make_qr_png(url: str) -> bytes:
    import qrcode
    q = qrcode.QRCode(box_size=8, border=3)
    q.add_data(url)
    q.make(fit=True)
    buf = io.BytesIO()
    q.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


async def start_qr(bot, uid, chat):
    await cleanup_login(uid)
    try:
        make_qr_png("tg://login?token=x")
    except ImportError:
        return await bot.send(chat, "❌ ورود با QR روی این سرور فعال نیست (کتابخونه‌ی qrcode نصب نیست). با شماره وارد شو.")
    client = make_client()
    await client.connect()
    qr = await client.qr_login()
    res = await bot.upload("sendPhoto", {"chat_id": chat, "caption": QR_CAPTION, "parse_mode": "HTML"}, "photo", "qr.png", make_qr_png(qr.url))
    st = {"step": "qr", "ts": time.time(), "chat": chat, "client": client, "qr": qr, "mid": res.get("message_id")}
    LOGIN[uid] = st
    st["task"] = asyncio.create_task(qr_wait(bot, uid))


async def qr_wait(bot, uid):
    st = LOGIN.get(uid)
    if not st:
        return
    chat = st["chat"]
    try:
        for i in range(6):  # حدود ۳ دقیقه
            try:
                await st["qr"].wait(30)
            except asyncio.TimeoutError:
                if LOGIN.get(uid) is not st:
                    return
                if i == 5:  # دور آخر: دیگه نو نمی‌کنیم
                    break
                await st["qr"].recreate()
                st["ts"] = time.time()
                await bot.upload("editMessageMedia", {
                    "chat_id": chat, "message_id": st["mid"],
                    "media": json.dumps({"type": "photo", "media": "attach://file", "caption": QR_CAPTION, "parse_mode": "HTML"})},
                    "file", "qr.png", make_qr_png(st["qr"].url))
                continue
            except SessionPasswordNeededError:
                st["step"] = "pw"
                return await bot.send(chat, "🔐 رمز تأیید دومرحله‌ای (2FA) رو بفرست. پیامت بعد از خوندن پاک می‌شه.")
            if st.get("mid"):
                await bot.delete(chat, st["mid"])
            return await finish_login(bot, uid, chat)
        await cleanup_login(uid)
        await bot.send(chat, "⌛ QR منقضی شد. دوباره /connect")
    except asyncio.CancelledError:
        raise
    except FloodWaitError as e:
        await cleanup_login(uid)
        await bot.send(chat, f"⏳ تلگرام موقتاً محدود کرد؛ {fmt_dur(e.seconds)} دیگه امتحان کن.")
    except Exception as e:  # noqa
        log.warning("[u%s] qr login failed: %r", uid, e)
        await cleanup_login(uid)
        await bot.send(chat, "❌ ورود با QR انجام نشد. دوباره /connect یا با شماره وارد شو.")


USER_CMDS = {"/panel": cmd_panel, "/status": cmd_status, "/cmd": cmd_cmd, "/restart": cmd_restart, "/stop": cmd_stop,
             "/run": cmd_run, "/disconnect": cmd_disconnect, "/cancel": cmd_cancel, "/backup": cmd_backup,
             "/backup_full": cmd_backup_full, "/restore": cmd_restore,
             "/app": cmd_app, "/miniapp": cmd_app}
ADMIN_CMDS = {"/users": cmd_users, "/allow": cmd_allow, "/extend": cmd_extend, "/revoke": cmd_revoke, "/log": cmd_log,
              "/broadcast": cmd_broadcast, "/dump": cmd_dump, "/open": cmd_open}


async def handle_manage(bot, uid, cid, mid, qid, action):
    """دکمه‌های مدیریتی mg:* روی پنل."""
    if action == "status":
        await bot.answer(qid)
        return await bot.edit(cid, mid, status_text(uid), {"inline_keyboard": [
            [botpanel.btn("🔙 بازگشت به پنل", "m", "primary")]]})
    if action == "run":
        await bot.answer(qid, "در حال روشن کردن...")
        await cmd_run(bot, uid, cid, "")
        return await bot.edit(cid, mid, main_text(uid), main_keyboard(uid))
    if action == "stop":
        await bot.answer(qid, "خاموش شد")
        await cmd_stop(bot, uid, cid, "")
        return await bot.edit(cid, mid, main_text(uid), main_keyboard(uid))
    if action == "restart":
        await bot.answer(qid, "در حال ریستارت...")
        await cmd_restart(bot, uid, cid, "")
        return await bot.edit(cid, mid, main_text(uid), main_keyboard(uid))
    if action == "backup":
        await bot.answer(qid)
        await cmd_backup(bot, uid, cid, "")
        return
    if action == "restore_last":
        await bot.answer(qid)
        p = latest_backup(uid)
        if not p:
            return await bot.send(cid, "❌ بکاپ خودکاری برات ثبت نشده. با /backup اول یکی بساز.")
        await bot.send(cid, "✅ " + await do_restore(uid, read_json(p, None)))
        return
    if action == "help":
        await bot.answer(qid)
        return await bot.send(cid, HELP + (ADMIN_HELP if uid == ADMIN else ""))
    if action == "app":
        await bot.answer(qid)
        return await cmd_app(bot, uid, cid, "")
    await bot.answer(qid)


async def request_access(bot, msg):
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    user = msg["from"]
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
    uname = f"@{user['username']}" if user.get("username") else "—"
    now = time.time()
    if now - REQ_TS.get(uid, 0) < 3600:
        return await bot.send(chat, "⏳ درخواستت قبلاً برای ادمین رفته؛ منتظر تأیید باش.")
    REQ_TS[uid] = now
    renew = get_entry(uid) is not None  # قبلاً کاربر بوده و اشتراکش تموم شده
    if renew:
        await bot.send(chat, f"⌛ اشتراکت تموم شده. درخواست تمدید برای ادمین رفت. آیدی تو: <code>{uid}</code>")
    else:
        await bot.send(chat, f"🔒 این بات خصوصیه. آیدی تو: <code>{uid}</code>\nدرخواستت برای ادمین ارسال شد.")
    if ADMIN:
        await bot.send(ADMIN, f"{'🔄 درخواست تمدید' if renew else '🔔 درخواست دسترسی'}\nنام: {html.escape(name)}\n"
                              f"یوزرنیم: {html.escape(uname)}\nآیدی: <code>{uid}</code>", ACCESS_KB(uid))


async def on_message(bot, msg):
    chat = msg.get("chat", {})
    if chat.get("type") != "private" or "from" not in msg:
        return
    uid, cid = msg["from"]["id"], chat["id"]
    text = (msg.get("text") or msg.get("caption") or "").strip()
    # مراحل ورود (شماره/کد/رمز): قبل از هر چیز؛ پیام‌های حساس بعد از خوندن پاک می‌شن
    if uid in LOGIN and not text.startswith("/") and is_allowed(uid):
        return await handle_login(bot, msg)
    if not text.startswith("/"):
        return
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    arg = arg.strip()
    if cmd == "/start":
        return await send_start(bot, uid, cid)
    if cmd == "/help":
        if is_allowed(uid):
            return await bot.send(cid, HELP + (ADMIN_HELP if uid == ADMIN else ""))
        return await bot.send(cid, PUBLIC_HELP, public_start_kb(uid))
    if cmd == "/cancel":
        return await cmd_cancel(bot, uid, cid, arg)
    if uid == ADMIN and msg.get("document") and text.split("@")[0].lower().startswith("/update"):
        return await do_update(bot, uid, cid, msg["document"])
    # دستور ناشناخته: نادیده گرفته می‌شه و کاربر رو ثبت‌نام نمی‌کنه (مثلاً /deploy قدیمی)
    is_restore_doc = bool(msg.get("document")) and text.split("@")[0].lower().startswith("/restore")
    if not (cmd == "/connect" or cmd in USER_CMDS or cmd in ADMIN_CMDS or is_restore_doc):
        return
    # از اینجا به بعد باید دسترسی داشته باشه؛ ثبت‌نام باز ← خودکار ثبت می‌شه
    if not await ensure_access(bot, msg):
        return
    if msg.get("document") and text.split("@")[0].lower().startswith("/restore"):
        # بکاپ کامل زیپ حتی بدون سشن قبلی قبول می‌شه (سشن رو برمی‌گردونه)
        return await restore_from_doc(bot, uid, cid, msg["document"])
    if cmd == "/connect":
        return await begin_login(bot, uid, cid)
    if cmd in USER_CMDS:
        return await USER_CMDS[cmd](bot, uid, cid, arg)
    if cmd in ADMIN_CMDS and uid == ADMIN:
        return await ADMIN_CMDS[cmd](bot, uid, cid, arg)


async def on_callback(bot, q):
    uid, data = q["from"]["id"], q.get("data", "")
    msg = q.get("message") or {}
    cid, mid = msg.get("chat", {}).get("id"), msg.get("message_id")
    kind, _, rest = data.partition(":")
    # دکمه‌های عمومی شروع (برای همه؛ ثبت‌نام باز خودکار انجام می‌شه)
    if kind == "ob":
        if rest == "go":
            await bot.answer(q["id"])
            if not await ensure_access(bot, {"from": q["from"], "chat": {"id": cid}}):
                return
            return await begin_login(bot, uid, cid)
        return await bot.answer(q["id"])
    if kind == "st":
        if rest == "features":
            await bot.answer(q["id"])
            return await bot.edit(cid, mid, FEATURES_PUBLIC,
                                  {"inline_keyboard": [[botpanel.btn("🚀 ساخت سلف من", "ob:go", "success")],
                                                       [botpanel.btn("🔙 بازگشت", "st:back", "primary")]]})
        if rest == "help":
            await bot.answer(q["id"])
            return await bot.edit(cid, mid, PUBLIC_HELP, public_start_kb(uid))
        if rest == "back":
            await bot.answer(q["id"])
            return await bot.edit(cid, mid, START_PUBLIC, public_start_kb(uid))
        return await bot.answer(q["id"])
    if not is_allowed(uid) and not (uid == ADMIN):
        return await bot.answer(q["id"], "اول «🚀 ساخت سلف من» رو بزن (/start)")
    if kind in ("ok", "no") and uid == ADMIN and rest.split(":")[0].isdigit():
        parts = rest.split(":")
        target = int(parts[0])
        if kind == "ok":
            days = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            allow_user(target, "", days)
            revive(target)
            dur = f"{days} روز" if days else "نامحدود"
            await bot.answer(q["id"], "✅ تأیید شد")
            await bot.edit(cid, mid, f"✅ دسترسی <code>{target}</code> تأیید شد ({dur})")
            try:
                await bot.send(target, f"✅ ادمین دسترسی‌ات رو تأیید کرد ({dur}). /connect برای وصل کردن اکانت یا /help")
            except Exception:  # noqa
                pass
        else:
            await bot.answer(q["id"], "رد شد")
            await bot.edit(cid, mid, f"❌ درخواست <code>{target}</code> رد شد")
        return
    if data == "go":
        await bot.answer(q["id"])
        return await bot.edit(cid, mid, "چطور وارد بشی؟\n\n🔳 <b>QR</b>: نیاز به یه دستگاه دیگه‌ی لاگین (بدون کد، بدون خطر باطل شدن)\n📱 <b>شماره</b>: کد تلگرام رو با خط تیره می‌فرستی\n🌐 <b>صفحه‌ی وب</b>: شماره و کد رو توی یه صفحه وارد می‌کنی (کد باطل نمی‌شه)", method_keyboard(uid))
    if data == "ph":
        await bot.answer(q["id"])
        await bot.edit(cid, mid, "👍 با شماره")
        return await ask_phone(bot, uid, cid)
    if data == "rs":
        st = LOGIN.get(uid)
        if not st or st.get("step") != "code":
            return await bot.answer(q["id"], "الان کدی منتظر نیست")
        await bot.answer(q["id"], "در حال ارسال دوباره...")
        try:
            sent = await st["client"](ResendCodeRequest(st["phone"], st["hash"]))
            st["hash"] = sent.phone_code_hash
            text, kb = code_prompt(sent)
            return await bot.send(cid, "🔁 دوباره فرستاده شد.\n\n" + text, kb)
        except Exception as e:  # noqa
            log.warning("[u%s] resend failed: %r", uid, e)
            return await bot.send(cid, login_error_text(e))
    if data == "qr":
        await bot.answer(q["id"])
        await bot.edit(cid, mid, "👍 با QR")
        return await start_qr(bot, uid, cid)
    if data == "dc":
        await bot.answer(q["id"], "در حال حذف...")
        await do_disconnect(uid)
        return await bot.edit(cid, mid, "🗑 اکانتت قطع شد و اطلاعاتت پاک شد. هر وقت خواستی /connect")
    if data == "x":
        await bot.answer(q["id"])
        return await bot.edit(cid, mid, "🔒 بسته شد. /start برای باز کردن دوباره", {"inline_keyboard": []})
    if kind == "mg":
        if not has_session(uid):
            return await bot.answer(q["id"], "اول /connect")
        return await handle_manage(bot, uid, cid, mid, q["id"], rest)
    if not has_session(uid):
        return await bot.answer(q["id"], "اول /connect")
    if data == "m":
        await bot.answer(q["id"])
        return await bot.edit(cid, mid, main_text(uid), main_keyboard(uid))
    if kind == "f" and rest in FEAT and rest not in HIDDEN:
        await bot.answer(q["id"])
        return await bot.edit(cid, mid, feat_text(uid, rest), feat_keyboard(rest))
    if kind == "t":
        key, _, v = rest.partition(":")
        if key in FEAT and set_flag(uid, key, v == "1"):
            await bot.answer(q["id"], "✅ انجام شد")
            # تأیید لحظه‌ای: پیش‌نمایش با مقدار جدید (سلف خودش چند ثانیه بعد اعمال می‌کنه)
            f = FEAT[key]
            ex = "\n".join(f"<code>{html.escape(e)}</code>" for e in f["examples"])
            status = "🟢 روشن" if v == "1" else "🔴 خاموش"
            return await bot.edit(cid, mid, f"{f['emoji']} <b>{html.escape(f['name'])}</b>\nوضعیت: {status}\n\n"
                                            f"{html.escape(f['desc'])}\n\n<b>نمونه:</b>\n{ex}", feat_keyboard(key))
    await bot.answer(q["id"])


# ───────────── مینی‌اپ (Telegram WebApp) ─────────────
# هر کاربر از داخل همین باتِ مشترک، بدون بات جدا، سلف خودش رو لمسی کنترل می‌کنه:
# وضعیت، روشن/خاموش/ریستارت، همه‌ی قابلیت‌ها + بازی‌ها، اجرای دستور توی چت، بکاپ/بازیابی.
# احراز هویت با initData تلگرام (HMAC با توکن بات) — جعل‌ناپذیر.
def verify_init_data(init_data: str, max_age: int = 86400):
    """(user_id, user_dict) یا (None, None) اگه امضا نامعتبر باشه."""
    try:
        params = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        recv_hash = params.pop("hash", "")
        if not recv_hash or not TOKEN:
            return None, None
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv_hash):
            return None, None
        try:
            auth_date = int(params.get("auth_date", "0"))
            if auth_date and time.time() - auth_date > max_age:
                return None, None
        except ValueError:
            return None, None
        user = json.loads(params.get("user", "{}"))
        uid = int(user.get("id", 0))
        return (uid, user) if uid else (None, None)
    except Exception:  # noqa
        return None, None


async def webapp_user(request):
    try:
        body = await request.json()
    except Exception:  # noqa
        return None, web.json_response({"ok": False, "error": "bad json"}, status=400)
    uid, tg_user = verify_init_data(body.get("initData", ""))
    if not uid:
        return None, web.json_response({"ok": False, "error": "احراز هویت تلگرام نامعتبره؛ مینی‌اپ رو از داخل همین بات باز کن"}, status=401)
    if not is_allowed(uid):
        return None, web.json_response({"ok": False, "error": "هنوز سلفی نساختی. توی بات /start بزن و «ساخت سلف من» رو بزن"}, status=403)
    body["_tg_user"] = tg_user  # اطلاعات امضاشده‌ی تلگرام (اسم/یوزرنیم/عکس) برای fallback
    return (uid, body), None


def avatar_data_url(uid):
    try:
        p = upath(uid, "avatar.jpg")
        if os.path.getsize(p) > 120_000:
            return None
        with open(p, "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()
    except OSError:
        return None


def webapp_profile(uid, tg_user=None) -> dict | None:
    """اسم/عکس اکانت برای هدر مینی‌اپ: profile.json + avatar.jpg (سلف خودش می‌نویسه)؛ نبود ← اطلاعات امضاشده‌ی تلگرام."""
    p = read_json(upath(uid, "profile.json"), None)
    photo = avatar_data_url(uid)
    if isinstance(p, dict) and p.get("id"):
        return {"name": p.get("name") or "—", "username": p.get("username"), "id": p.get("id"), "photo": photo}
    nm = ""
    un = None
    if isinstance(tg_user, dict) and tg_user.get("id") == uid:
        nm = " ".join(x for x in (tg_user.get("first_name"), tg_user.get("last_name")) if x)
        un = tg_user.get("username")
    return {"name": nm or un or "—", "username": un, "id": uid, "photo": photo}


def webapp_snapshot(uid, tg_user=None) -> dict:
    inst = INSTANCES.get(uid)
    st = read_status(uid)
    running = bool(inst and inst.running)
    fresh = bool(st and time.time() - st.get("ts", 0) < 40)
    flags = read_flags(uid)
    feats = [{"key": k, "name": FEAT[k]["name"], "emoji": FEAT[k]["emoji"], "toggle": FEAT[k]["toggle"],
              "on": bool(flags.get(k)), "desc": FEAT[k]["desc"]} for k in FEAT if k not in HIDDEN]
    return {
        "uid": uid,
        "mode": "hub",
        "caps": {"run_stop": True, "restore_last": True},
        "me": webapp_profile(uid, tg_user),
        "sub": sub_text(uid),
        "domain": DOMAIN.replace("https://", "").replace("http://", ""),
        "has_session": has_session(uid),
        "running": running,
        "failed": bool(inst and inst.failed),
        "uptime": int(time.time() - inst.started) if running else 0,
        "ram": round(inst.rss() or 0) if running and inst.rss() else None,
        "restarts": (st.get("restarts", 0) if isinstance(st, dict) else 0),
        "pending": 0,
        "authorized": bool(st.get("authorized")) if fresh else None,
        "loops": st.get("loops") if fresh else {},
        "on_count": sum(1 for v in flags.values() if v),
        "total": len(feats),
        "feats": feats,
    }


async def api_me(request):
    auth, err = await webapp_user(request)
    if err:
        return err
    uid, body = auth
    if not has_session(uid):
        return web.json_response({"ok": True, "connected": False, "sub": sub_text(uid),
                                  "hint": "هنوز اکانت وصل نکردی؛ توی بات /connect بزن",
                                  "login_url": web_login_url(uid)})
    d = webapp_snapshot(uid, body.get("_tg_user"))
    d.update(ok=True, connected=True)
    return web.json_response(d)


async def api_toggle(request):
    auth, err = await webapp_user(request)
    if err:
        return err
    uid, body = auth
    key, val = body.get("key", ""), bool(body.get("value"))
    if not set_flag(uid, key, val):
        return web.json_response({"ok": False, "error": "کلید نامعتبره"}, status=400)
    return web.json_response({"ok": True, **webapp_snapshot(uid)})


async def api_control(request):
    auth, err = await webapp_user(request)
    if err:
        return err
    uid, body = auth
    act = str(body.get("action", "")).lower()
    inst = get_instance(uid)
    if act == "run":
        if not has_session(uid):
            return web.json_response({"ok": False, "error": "اول /connect"}, status=400)
        if not is_allowed(uid):
            return web.json_response({"ok": False, "error": "اشتراکت تموم شده"}, status=403)
        try:
            os.remove(stopped_marker(uid))
        except OSError:
            pass
        inst.start()
        return web.json_response({"ok": True, "msg": "🟢 سلف داره بالا میاد...", **webapp_snapshot(uid)})
    if act == "stop":
        await inst.stop()
        try:
            open(stopped_marker(uid), "w").close()
        except OSError:
            pass
        return web.json_response({"ok": True, "msg": "🔴 سلف متوقف شد", **webapp_snapshot(uid)})
    if act == "restart":
        if not has_session(uid):
            return web.json_response({"ok": False, "error": "اول /connect"}, status=400)
        await inst.stop()
        try:
            os.remove(stopped_marker(uid))
        except OSError:
            pass
        inst.start()
        return web.json_response({"ok": True, "msg": "🔄 داره ریستارت می‌شه...", **webapp_snapshot(uid)})
    return web.json_response({"ok": False, "error": "action نامعتبره"}, status=400)


async def api_cmd(request):
    auth, err = await webapp_user(request)
    if err:
        return err
    uid, body = auth
    target = str(body.get("target", "me")).strip() or "me"
    text = str(body.get("text", "")).strip()[:500]
    if not text:
        return web.json_response({"ok": False, "error": "دستور خالیه"}, status=400)
    inst = INSTANCES.get(uid)
    if not (inst and inst.running):
        return web.json_response({"ok": False, "error": "سلفت روشن نیست؛ اول روشنش کن"}, status=400)
    if target.lower() != "me" and not (target.startswith("@") or target.lstrip("-").isdigit()):
        return web.json_response({"ok": False, "error": "هدف باید me یا @username یا آیدی عددی باشه"}, status=400)
    ctl_send(uid, op="run", chat=target, text=text)
    return web.json_response({"ok": True, "msg": f"✅ به {target} فرستاده شد"})


async def api_backup(request):
    auth, err = await webapp_user(request)
    if err:
        return err
    uid, _ = auth
    data = sanitized_settings(uid)
    if data is None:
        return web.json_response({"ok": False, "error": "تنظیماتی نداری"}, status=400)
    return web.json_response({"ok": True, "backup": data})


async def api_restore(request):
    auth, err = await webapp_user(request)
    if err:
        return err
    uid, body = auth
    obj = body.get("backup")
    if not isinstance(obj, dict):
        return web.json_response({"ok": False, "error": "فایل بکاپ نامعتبره"}, status=400)
    try:
        msg = await do_restore(uid, obj)
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    return web.json_response({"ok": True, "msg": "✅ " + msg, **webapp_snapshot(uid)})


async def api_restore_last(request):
    """برگردوندن آخرین بکاپ خودکار سرور — بدون نیاز به آپلود فایل."""
    auth, err = await webapp_user(request)
    if err:
        return err
    uid, _ = auth
    p = latest_backup(uid)
    if not p:
        return web.json_response({"ok": False, "error": "بکاپ خودکاری برات ثبت نشده؛ اول توی بات /backup بزن"}, status=400)
    try:
        msg = await do_restore(uid, read_json(p, None))
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    return web.json_response({"ok": True, "msg": "✅ " + msg, **webapp_snapshot(uid)})


MINIAPP_HTML = miniapp.HTML  # صفحه‌ی مشترک مینی‌اپ (miniapp.py) — هدر اکانت/تایم همین‌جاست
# (صفحه‌ی مینی‌اپ به miniapp.py منتقل شد؛ MINIAPP_HTML از اون میاد)


async def serve_app(request):
    return web.Response(text=MINIAPP_HTML, content_type="text/html")








async def handle_update(bot, u):
    if "callback_query" in u:
        await on_callback(bot, u["callback_query"])
    elif "message" in u:
        await on_message(bot, u["message"])


BOT_COMMANDS = [
    {"command": "start", "description": "🚀 شروع / ساخت سلف من"},
    {"command": "panel", "description": "🎛 پنل مدیریتی (روشن/خاموش، قابلیت‌ها، بکاپ)"},
    {"command": "status", "description": "📊 وضعیت سلف"},
    {"command": "app", "description": "📱 مینی‌اپ (کنترل لمسی)"},
    {"command": "connect", "description": "🔌 وصل کردن اکانت"},
    {"command": "cmd", "description": "⚡ اجرای دستور (مثال: /cmd me .میویی)"},
    {"command": "run", "description": "🟢 روشن کردن سلف"},
    {"command": "stop", "description": "🔴 خاموش کردن سلف"},
    {"command": "restart", "description": "🔄 ریستارت سلف"},
    {"command": "backup", "description": "💾 بکاپ تنظیمات"},
    {"command": "backup_full", "description": "💾 بکاپ کامل (با سشن)"},
    {"command": "restore", "description": "♻️ بازیابی (/restore last)"},
    {"command": "disconnect", "description": "🗑 خروج و حذف اطلاعات"},
]


async def setup_bot_menu(bot):
    try:
        await bot.api("setMyCommands", commands=BOT_COMMANDS)
    except Exception as e:  # noqa
        log.warning("setMyCommands failed: %r", e)
    url = app_base_url()
    if url:
        try:
            await bot.api("setChatMenuButton", menu_button={"type": "web_app", "text": "📱 مینی‌اپ", "web_app": {"url": url}})
            log.info("menu button -> %s", url)
        except Exception as e:  # noqa
            log.warning("setChatMenuButton failed: %r (شاید بات هنوز WebApp نداره؛ توی BotFather /newapp بزن)", e)


async def poll(app):
    while True:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
                bot = Bot(s)
                _bot_ref["bot"] = bot
                me = await bot.api("getMe")
                BOT_STATE.update(ok=True, error="")
                await bot.api("deleteWebhook")
                log.info("hub bot: @%s admin=%s", me.get("username"), ADMIN)
                await setup_bot_menu(bot)
                offset = None
                while True:
                    await purge_logins()
                    ups = await bot.api("getUpdates", offset=offset, timeout=25, allowed_updates=["message", "callback_query"])
                    for u in ups:
                        offset = u["update_id"] + 1
                        try:
                            await handle_update(bot, u)
                        except Exception as e:  # noqa
                            log.warning("hub update failed: %r", e)
        except asyncio.CancelledError:
            raise
        except botpanel.BotError as e:
            if e.code in (401, 404):
                BOT_STATE.update(ok=False, error="توکن بات نامعتبره: HUB_BOT_TOKEN اشتباهه یا BotFather باطلش کرده (/revoke). "
                                                 "توکن جدید رو دقیق کپی کن (بدون فاصله و گیومه).")
                log.error("hub bot token rejected by Telegram: %s", e)
            else:
                BOT_STATE.update(ok=False, error=f"خطای Bot API: {e}")
                log.warning("hub bot: %s", e)
            await asyncio.sleep(60 if e.code in (401, 404) else 10)
        except Exception as e:  # noqa
            BOT_STATE.update(ok=False, error=f"اتصال به تلگرام برقرار نشد: {type(e).__name__}")
            log.warning("hub bot: %r", e)
            await asyncio.sleep(10)


# ───────────── ورود از صفحه‌ی وب ─────────────
WEB_TOKENS = {}  # token -> {"uid", "exp", "hits"}
WEB_TTL = 900
WEB_MAX_HITS = 60


def web_login_url(uid) -> str:
    """لینک یک‌بارمصرف ورود وب برای این کاربر (خالی = دامنه‌ی عمومی معلوم نیست)."""
    if not DOMAIN:
        return ""
    now = time.time()
    for t in [t for t, v in WEB_TOKENS.items() if v["exp"] < now or v["uid"] == uid]:
        WEB_TOKENS.pop(t, None)  # توکن‌های منقضی و قبلیِ همین کاربر باطل می‌شن
    token = secrets.token_urlsafe(24)
    WEB_TOKENS[token] = {"uid": uid, "exp": now + WEB_TTL, "hits": 0}
    return f"{DOMAIN.rstrip('/')}/login?t={token}"


def web_token_uid(token):
    """uid صاحب توکن یا None (منقضی/ناشناخته/بیش از حد استفاده شده/دسترسی ندارد)."""
    v = WEB_TOKENS.get(token or "")
    if not v:
        return None
    if v["exp"] < time.time() or v["hits"] >= WEB_MAX_HITS or not is_allowed(v["uid"]):
        WEB_TOKENS.pop(token, None)
        return None
    v["hits"] += 1
    return v["uid"]


def _plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or ""))


def web_headers() -> dict:
    return {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY"}


def web_html(body: str, status: int = 200) -> web.Response:
    return web.Response(text=body, status=status, content_type="text/html", headers=web_headers())


def bot_username() -> str:
    return botpanel.BOT.get("username") or ""


async def web_do_phone(uid, phone_raw, consent):
    """→ (صفحه‌ی بعدی، پیام، ok)."""
    if not consent:
        return "phone", "برای ادامه باید شرایط رو قبول کنی.", False
    if has_session(uid):
        return "done", "", True
    if not (API_ID and API_HASH):
        return "phone", "ادمین هنوز API_ID/API_HASH رو تنظیم نکرده.", False
    if uid != ADMIN and len(connected_users()) >= MAX_USERS:
        return "phone", "ظرفیت هاب پره؛ به ادمین خبر بده.", False
    phone = parse_phone(phone_raw)
    if not phone:
        return "phone", "شماره معتبر نیست؛ مثلاً +989121234567 یا 09121234567", False
    await cleanup_login(uid)
    client = make_client()
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
    except Exception as e:  # noqa
        log.warning("[u%s] web login send_code failed: %r", uid, e)
        try:
            await client.disconnect()
        except Exception:  # noqa
            pass
        msg = _plain(login_error_text(e))
        return "phone", msg, False
    how, nxt = core.sent_code_info(sent)
    LOGIN[uid] = {"step": "code", "ts": time.time(), "chat": uid, "client": client, "phone": phone,
                  "hash": sent.phone_code_hash, "web": True, "how": how, "nxt": nxt}
    return "code", f"کد فرستاده شد: {how}", True


async def web_do_code(uid, code_raw):
    st = LOGIN.get(uid)
    if not st or st.get("step") != "code":
        return "phone", "نشست ورود پیدا نشد؛ دوباره شماره رو وارد کن.", False
    st["ts"] = time.time()
    code = re.sub(r"\D", "", num(code_raw or ""))
    if not code:
        return "code", "فقط عدد کد رو وارد کن.", False
    try:
        await st["client"].sign_in(phone=st["phone"], code=code, phone_code_hash=st["hash"])
    except SessionPasswordNeededError:
        st["step"] = "pw"
        return "pw", "", True
    except PhoneCodeInvalidError:
        return "code", "کد اشتباهه؛ دوباره وارد کن.", False
    except PhoneCodeExpiredError:
        await cleanup_login(uid)
        return "phone", "کد منقضی شد. دوباره شماره رو وارد کن تا کد جدید بیاد.", False
    except FloodWaitError as e:
        await cleanup_login(uid)
        return "phone", f"تلگرام موقتاً محدود کرد؛ {fmt_dur(e.seconds)} دیگه امتحان کن.", False
    except Exception as e:  # noqa
        log.warning("[u%s] web login code error: %r", uid, e)
        return "code", _plain(login_error_text(e)), False
    return await web_finish(uid)


async def web_do_pw(uid, password):
    st = LOGIN.get(uid)
    if not st or st.get("step") != "pw":
        return "phone", "نشست ورود پیدا نشد؛ دوباره شماره رو وارد کن.", False
    st["ts"] = time.time()
    try:
        await st["client"].sign_in(password=password or "")
    except PasswordHashInvalidError:
        return "pw", "رمز اشتباهه؛ دوباره وارد کن.", False
    except FloodWaitError as e:
        await cleanup_login(uid)
        return "phone", f"تلگرام موقتاً محدود کرد؛ {fmt_dur(e.seconds)} دیگه امتحان کن.", False
    except Exception as e:  # noqa
        log.warning("[u%s] web login 2fa error: %r", uid, e)
        return "pw", _plain(login_error_text(e)), False
    return await web_finish(uid)


async def web_do_resend(uid):
    st = LOGIN.get(uid)
    if not st or st.get("step") != "code":
        return "phone", "نشست ورود پیدا نشد؛ دوباره شماره رو وارد کن.", False
    try:
        sent = await st["client"](ResendCodeRequest(st["phone"], st["hash"]))
    except Exception as e:  # noqa
        log.warning("[u%s] web login resend failed: %r", uid, e)
        return "code", _plain(login_error_text(e)), False
    how, nxt = core.sent_code_info(sent)
    st.update(hash=sent.phone_code_hash, how=how, nxt=nxt)
    return "code", f"دوباره فرستاده شد: {how}", True


async def web_finish(uid):
    bot = _bot_ref.get("bot")
    try:
        await finish_login(bot, uid, uid) if bot else await _finish_login_quiet(uid)
    except Exception as e:  # noqa
        log.warning("[u%s] web login finish failed: %r", uid, e)
        return "code", _plain(login_error_text(e)), False
    for t in [t for t, v in WEB_TOKENS.items() if v["uid"] == uid]:
        WEB_TOKENS.pop(t, None)  # لینک بعد از ورود موفق باطل می‌شه
    return "done", "", True


async def _finish_login_quiet(uid):
    class _Mute:
        async def send(self, *a, **k):
            return None
        async def delete(self, *a, **k):
            return None
    await finish_login(_Mute(), uid, uid)


def web_render(step, token, msg="", ok=False, uid=None):
    st = LOGIN.get(uid) or {}
    if step == "code":
        nxt = st.get("nxt") or ""
        if msg and not ok:  # خطا (مثلاً کد اشتباه)؛ فرم کد می‌مونه
            return weblogin.code_page(token, "", True, nxt, msg)
        return weblogin.code_page(token, msg or f"کد فرستاده شد: {st.get('how', '')}", True, nxt)
    if step == "pw":
        return weblogin.pw_page(token, msg)
    if step == "done":
        prof = read_json(upath(uid, "profile.json"), {}) if uid else {}
        return weblogin.done_page(prof.get("name", ""), bot_username())
    return weblogin.phone_page(token, msg, ok, core.api_hint())


async def web_login_page(request):
    token = request.query.get("t", "")
    uid = web_token_uid(token)
    if not uid:
        return web_html(weblogin.invalid_page(bot_username()), 403)
    if has_session(uid):
        return web_html(web_render("done", token, uid=uid))
    st = LOGIN.get(uid)
    step = st["step"] if st and st.get("web") and st.get("step") in ("code", "pw") else "phone"
    return web_html(web_render(step, token, uid=uid))


async def web_login_post(request):
    action = request.match_info["action"]
    try:
        form = await request.post()
    except Exception:  # noqa
        return web_html(weblogin.invalid_page(bot_username()), 400)
    token = str(form.get("t", ""))
    uid = web_token_uid(token)
    if not uid:
        return web_html(weblogin.invalid_page(bot_username()), 403)
    if action == "phone":
        step, msg, ok = await web_do_phone(uid, str(form.get("phone", "")), form.get("consent") == "on")
    elif action == "code":
        step, msg, ok = await web_do_code(uid, str(form.get("code", "")))
    elif action == "2fa":
        step, msg, ok = await web_do_pw(uid, str(form.get("password", "")))
    elif action == "resend":
        step, msg, ok = await web_do_resend(uid)
    else:
        return web_html(weblogin.invalid_page(bot_username()), 404)
    return web_html(web_render(step, token, msg, ok, uid))


async def health(request):
    wants_html = "text/html" in request.headers.get("Accept", "") and request.query.get("json") != "1"
    if wants_html:  # مرورگر: صفحه‌ی خوشامد + راهنمای ورود؛ healthcheck/curl همچنان JSON می‌گیره
        return web_html(weblogin.landing_page(bot_username()))
    return web.json_response({"hub": True, "single_bot": True, "bot": dict(BOT_STATE), "open": is_open(),
                              "running": sum(1 for i in INSTANCES.values() if i.running),
                              "users": len(connected_users()), "app": bool(app_base_url())})


async def on_startup(app):
    migrate_admin()
    kill_stale()
    app["tasks"] = [asyncio.create_task(poll(app)), asyncio.create_task(start_all()), asyncio.create_task(updater.mark_healthy()),
                     asyncio.create_task(maintenance())]


async def on_cleanup(app):
    for t in app["tasks"]:
        t.cancel()
    await stop_all()


def main():
    configure()
    if not TOKEN or not ADMIN:
        raise SystemExit("HUB_BOT_TOKEN و HUB_ADMIN_ID لازمه")
    app = web.Application()
    app.add_routes([
        web.get("/", health),
        web.get("/app", serve_app),
        web.get("/font/vazirmatn.woff2", miniapp.serve_font),
        web.get("/login", web_login_page),
        web.post("/login/{action}", web_login_post),
        web.post("/api/me", api_me),
        web.post("/api/toggle", api_toggle),
        web.post("/api/control", api_control),
        web.post("/api/cmd", api_cmd),
        web.post("/api/backup", api_backup),
        web.post("/api/restore", api_restore),
        web.post("/api/restore_last", api_restore_last),
    ])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
