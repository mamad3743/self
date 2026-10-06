"""هاب چندکاربره: یه بات مشترک؛ هر کس اکانت خودش رو وصل می‌کنه و سلفش توی یه پردازش جدا اجرا می‌شه.

فعال‌سازی (متغیرهای Railway):
  HUB_BOT_TOKEN = توکن بات (BotFather)      HUB_ADMIN_ID = آیدی عددی تو
  API_ID / API_HASH = از my.telegram.org     MAX_USERS = سقف کاربر (پیش‌فرض ۵)
  HUB_DIR = پوشه‌ی داده (پیش‌فرض /data/hub)   PROXY = اختیاری

هر کاربر: /data/hub/<id>/ شامل session.txt، settings.json، ctl.jsonl (صف دستور)، status.json.
دستورهای نقطه‌ای (.میویی و...) توی چت‌های خود کاربر مثل قبل کار می‌کنن؛ بات برای اتصال، پنل، وضعیت و مدیریته.
"""
import os
import re
import sys
import json
import time
import html
import shutil
import signal
import socket
import asyncio
import secrets
import collections

os.environ.setdefault("PANEL_PASSWORD", secrets.token_hex(12))  # core موقع import لازم داره

import aiohttp
from aiohttp import web
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, PhoneNumberInvalidError,
    PasswordHashInvalidError, FloodWaitError, ApiIdInvalidError, PhoneNumberBannedError,
)

import boot
import core
import botpanel
import meow
import updater
from core import FEATS, FEAT, GRID, log

REPO = os.environ.get("SELF_REPO_DIR") or os.path.dirname(os.path.abspath(__file__))
DEFAULT_FLAGS = dict(core.F)  # پیش‌فرض قابلیت‌ها (قبل از هر load_settings)
HIDDEN = {"update"}  # از پنل کاربرها مخفیه

TOKEN = ""
ADMIN = 0
DATA = "/data/hub"
MAX_USERS = 5
API_ID = 0
API_HASH = ""
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


def configure(env=None):
    global TOKEN, ADMIN, DATA, MAX_USERS, API_ID, API_HASH
    env = env if env is not None else os.environ
    TOKEN = env.get("HUB_BOT_TOKEN", "")
    ADMIN = int(env.get("HUB_ADMIN_ID") or 0)
    DATA = env.get("HUB_DIR", "/data/hub")
    MAX_USERS = int(env.get("MAX_USERS") or 5)
    core.load_api()
    API_ID = int(env.get("API_ID") or 0) or core.API["id"]
    API_HASH = env.get("API_HASH") or core.API["hash"]
    os.makedirs(DATA, exist_ok=True)


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


def is_allowed(uid) -> bool:
    return uid == ADMIN or str(uid) in load_reg()["allowed"]


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
        STATUS_FILE=upath(uid, "status.json"), PORT=str(free_port()), PANEL_PASSWORD=panel_password(uid),
        API_ID=str(API_ID), API_HASH=API_HASH, PYTHONUNBUFFERED="1",
    )
    # اگه هاب با نسخه‌ی بروزرسانی‌شده (/data/code) بالا اومده، سلف‌ها هم همونو اجرا کنن
    if os.environ.get("SELF_OVERLAY") and os.path.isdir(boot.CODE_DIR):
        env["HUB_CODE_DIR"] = boot.CODE_DIR
    else:
        env.pop("HUB_CODE_DIR", None)
    return env


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
        if os.path.exists(stopped_marker(uid)):
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
        return "🔌 هنوز اکانتی وصل نکردی. /connect"
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
    flags = read_flags(uid)
    on = [FEAT[k]["emoji"] + " " + FEAT[k]["name"] for k in FEAT if flags.get(k) and k not in HIDDEN and FEAT[k]["toggle"]]
    lines.append(f"\n🎛 قابلیت‌های روشن ({len(on)}): " + ("، ".join(on) if on else "—"))
    if fresh and st.get("loops"):
        run = "، ".join(f"{LOOP_NAMES.get(k, k)} در {n} چت" for k, n in st["loops"].items())
        lines.append(f"🔄 خودکارهای فعال: {run}")
    return "\n".join(lines)


def main_text(uid) -> str:
    flags = read_flags(uid)
    on = sum(1 for k, v in flags.items() if v and k not in HIDDEN)
    return ("⚙️ <b>پنل سلف تو</b>\n"
            f"✔ {len(FEATS) - len(HIDDEN)} قابلیت ({on} روشن)\n"
            "🟢 روشن   🔴 خاموش   🔵 دستوری\n\n"
            "روی هر دکمه بزن تا راهنما ببینی یا روشن/خاموشش کنی.\n"
            "دستورهای چت‌محور مثل <code>.میویی</code> رو توی همون چت بزن.")


def feat_style(f, flags) -> str:
    if not f["toggle"]:
        return "primary"
    return "success" if flags.get(f["key"]) else "danger"


def main_keyboard(uid) -> dict:
    flags = read_flags(uid)
    rows = []
    for row in GRID:
        keys = [k for k in row if k not in HIDDEN]
        if not keys:
            continue
        btns = [botpanel.btn(f"{FEAT[k]['emoji']} {FEAT[k]['name']}", f"f:{k}", feat_style(FEAT[k], flags)) for k in keys]
        rows.append(list(reversed(btns)))
    rows.append([botpanel.btn("❌ بستن پنل", "x", "danger")])
    return {"inline_keyboard": rows}


def feat_text(uid, key) -> str:
    f = FEAT[key]
    flags = read_flags(uid)
    status = ("🟢 روشن" if flags.get(key) else "🔴 خاموش") if f["toggle"] else "🔵 دستوری"
    ex = "\n".join(f"<code>{html.escape(e)}</code>" for e in f["examples"])
    return (f"{f['emoji']} <b>{html.escape(f['name'])}</b>\nوضعیت: {status}\n\n{html.escape(f['desc'])}\n\n<b>نمونه:</b>\n{ex}")


def feat_keyboard(key) -> dict:
    rows = []
    if FEAT[key]["toggle"]:
        rows.append([botpanel.btn("🔴 خاموش", f"t:{key}:0", "danger"), botpanel.btn("🟢 روشن", f"t:{key}:1", "success")])
    rows.append([botpanel.btn("🔙 بازگشت", "m", "primary"), botpanel.btn("❌ بستن", "x", "danger")])
    return {"inline_keyboard": rows}


HELP = (
    "🐾 <b>هاب سلف</b>\n\n"
    "اکانتت رو وصل می‌کنی، سلف مخصوص خودت روی سرور اجرا می‌شه و از همین بات کنترلش می‌کنی.\n\n"
    "/connect ← وصل کردن اکانت\n"
    "/panel ← پنل روشن/خاموش قابلیت‌ها\n"
    "/status ← وضعیت سلفت\n"
    "/cmd ← اجرای دستور توی یه چت، مثلاً <code>/cmd me .وضعیت چت</code> یا <code>/cmd @group .میویی</code>\n"
    "/restart ، /stop ، /run ← مدیریت سلف\n"
    "/disconnect ← خروج کامل و حذف اطلاعات\n\n"
    "بعد از وصل شدن، دستورهای نقطه‌ای (<code>.میویی</code> <code>.ماهیگیری</code> و...) رو توی خود تلگرامت بزن."
)
ADMIN_HELP = (
    "\n\n<b>ادمین:</b>\n/users ← لیست کاربرها\n/allow &lt;id&gt; [نام] ← دادن دسترسی\n/revoke &lt;id&gt; ← گرفتن دسترسی\n"
    "/log [id] ← آخرین لاگ سلف\nبروزرسانی: فایل زیپ رو با کپشن <code>/update</code> بفرست"
)
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
ACCESS_KB = lambda uid: {"inline_keyboard": [[botpanel.btn("✅ تأیید", f"ok:{uid}", "success"),
                                               botpanel.btn("❌ رد", f"no:{uid}", "danger")]]}


# ───────────── ورود اکانت ─────────────
def make_client():
    return TelegramClient(StringSession(), API_ID, API_HASH, **meow.proxy_kwargs(os.getenv("PROXY", "")))


async def cleanup_login(uid):
    st = LOGIN.pop(uid, None)
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


async def ask_phone(bot, uid, chat):
    LOGIN[uid] = {"step": "phone", "ts": time.time(), "chat": chat, "client": None}
    await bot.send(chat, "📱 شماره‌ی اکانتت رو با کد کشور بفرست (مثلاً <code>+989121234567</code>).\nلغو: /cancel")


def parse_phone(text):
    t = re.sub(r"[^\d+]", "", num(text))
    digits = t.lstrip("+")
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


async def handle_login(bot, msg):
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    st = LOGIN[uid]
    st["ts"] = time.time()
    text = (msg.get("text") or "").strip()
    await bot.delete(chat, msg["message_id"])  # شماره/کد/رمز نباید توی چت بمونه
    step = st["step"]
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
            return await bot.send(
                chat,
                "📩 کد تلگرام برات اومد (از چت «Telegram» توی همون اکانت).\n\n"
                "⚠️ <b>کد رو با فاصله یا خط تیره بنویس</b>، مثلاً <code>1-2-3-4-5</code>. "
                "اگه پشت‌سرهم بفرستی تلگرام کد رو باطل می‌کنه!")
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
    await bot.send(chat, f"✅ وصل شد: <b>{html.escape(name)}</b>\n\n"
                         "سلفت داره بالا میاد (حدود ۱۰ ثانیه). /status و /panel رو بزن.\n"
                         "بعدش توی یه چت میویی <code>.میویی</code> یا <code>.ماهیگیری</code> بزن.")


# ───────────── دستورها ─────────────
def need_connected(uid) -> bool:
    return has_session(uid)


async def cmd_panel(bot, uid, chat, arg):
    if not has_session(uid):
        return await bot.send(chat, "🔌 اول اکانتت رو وصل کن: /connect")
    await bot.send(chat, main_text(uid), main_keyboard(uid))


async def cmd_status(bot, uid, chat, arg):
    await bot.send(chat, status_text(uid))


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


async def cmd_restart(bot, uid, chat, arg):
    if not has_session(uid):
        return await bot.send(chat, "🔌 اول /connect")
    inst = get_instance(uid)
    await bot.send(chat, "🔄 دارم ریستارت می‌کنم...")
    await inst.stop()
    try:
        os.remove(stopped_marker(uid))
    except OSError:
        pass
    inst.start()


async def cmd_stop(bot, uid, chat, arg):
    if not has_session(uid):
        return await bot.send(chat, "🔌 اول /connect")
    await get_instance(uid).stop()
    open(stopped_marker(uid), "w").close()
    await bot.send(chat, "🔴 سلف متوقف شد. دوباره: /run")


async def cmd_run(bot, uid, chat, arg):
    if not has_session(uid):
        return await bot.send(chat, "🔌 اول /connect")
    try:
        os.remove(stopped_marker(uid))
    except OSError:
        pass
    get_instance(uid).start()
    await bot.send(chat, "🟢 سلف داره بالا میاد...")


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
    rows = []
    for u in ids:
        inst = INSTANCES.get(u)
        state_ = "🟢" if inst and inst.running else ("⚠️" if inst and inst.failed else ("🔴" if has_session(u) else "⚪️"))
        name = reg["allowed"].get(str(u), {}).get("name", "ادمین" if u == ADMIN else "")
        rows.append(f"{state_} <code>{u}</code> {html.escape(name or '')}")
    await bot.send(chat, f"👥 کاربرها ({len(connected_users())}/{MAX_USERS} وصل)\n\n" + "\n".join(rows) +
                   "\n\n🟢 در حال اجرا · 🔴 متوقف · ⚪️ اکانت وصل نکرده")


async def cmd_allow(bot, uid, chat, arg):
    parts = arg.split(maxsplit=1)
    if not parts or not parts[0].isdigit():
        return await bot.send(chat, "مثال: <code>/allow 123456789 علی</code>")
    target = int(parts[0])
    allow_user(target, parts[1] if len(parts) > 1 else "")
    await bot.send(chat, f"✅ دسترسی <code>{target}</code> داده شد")
    try:
        await bot.send(target, "✅ ادمین دسترسی‌ات رو تأیید کرد. /connect برای وصل کردن اکانت یا /help")
    except Exception:  # noqa
        pass


def allow_user(target, name=""):
    reg = load_reg()
    reg["allowed"][str(target)] = {"name": name, "since": int(time.time())}
    save_reg(reg)


async def cmd_revoke(bot, uid, chat, arg):
    if not arg.strip().isdigit():
        return await bot.send(chat, "مثال: <code>/revoke 123456789</code>")
    target = int(arg.strip())
    if target == ADMIN:
        return await bot.send(chat, "❌ ادمین رو نمی‌شه حذف کرد")
    reg = load_reg()
    reg["allowed"].pop(str(target), None)
    save_reg(reg)
    inst = INSTANCES.get(target)
    if inst:
        await inst.stop()
    open(stopped_marker(target), "w").close() if os.path.isdir(udir(target)) else None
    await bot.send(chat, f"✅ دسترسی <code>{target}</code> گرفته شد و سلفش متوقف شد (اطلاعاتش می‌مونه؛ حذف کامل: خودش /disconnect بزنه)")


async def cmd_log(bot, uid, chat, arg):
    target = int(arg.strip()) if arg.strip().isdigit() else uid
    inst = INSTANCES.get(target)
    lines = list(inst.logs)[-25:] if inst else []
    body = html.escape("\n".join(lines)[-3500:]) or "—"
    await bot.send(chat, f"📜 لاگ <code>{target}</code>:\n<pre>{body}</pre>")


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


USER_CMDS = {"/panel": cmd_panel, "/status": cmd_status, "/cmd": cmd_cmd, "/restart": cmd_restart, "/stop": cmd_stop,
             "/run": cmd_run, "/disconnect": cmd_disconnect, "/cancel": cmd_cancel}
ADMIN_CMDS = {"/users": cmd_users, "/allow": cmd_allow, "/revoke": cmd_revoke, "/log": cmd_log}


async def request_access(bot, msg):
    uid, chat = msg["from"]["id"], msg["chat"]["id"]
    user = msg["from"]
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
    uname = f"@{user['username']}" if user.get("username") else "—"
    now = time.time()
    if now - REQ_TS.get(uid, 0) < 3600:
        return await bot.send(chat, "⏳ درخواستت قبلاً برای ادمین رفته؛ منتظر تأیید باش.")
    REQ_TS[uid] = now
    await bot.send(chat, f"🔒 این بات خصوصیه. آیدی تو: <code>{uid}</code>\nدرخواستت برای ادمین ارسال شد.")
    if ADMIN:
        await bot.send(ADMIN, f"🔔 درخواست دسترسی\nنام: {html.escape(name)}\nیوزرنیم: {html.escape(uname)}\nآیدی: <code>{uid}</code>",
                       ACCESS_KB(uid))


async def on_message(bot, msg):
    chat = msg.get("chat", {})
    if chat.get("type") != "private" or "from" not in msg:
        return
    uid, cid = msg["from"]["id"], chat["id"]
    if not is_allowed(uid):
        return await request_access(bot, msg)
    text = (msg.get("text") or msg.get("caption") or "").strip()
    if uid == ADMIN and msg.get("document") and text.split("@")[0].lower().startswith("/update"):
        return await do_update(bot, uid, cid, msg["document"])
    if uid in LOGIN and not text.startswith("/"):
        return await handle_login(bot, msg)
    if not text.startswith("/"):
        return
    cmd, _, arg = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    if cmd in ("/start", "/help"):
        return await bot.send(cid, HELP + (ADMIN_HELP if uid == ADMIN else ""))
    if cmd == "/connect":
        return await begin_login(bot, uid, cid)
    if cmd in USER_CMDS:
        return await USER_CMDS[cmd](bot, uid, cid, arg.strip())
    if cmd in ADMIN_CMDS and uid == ADMIN:
        return await ADMIN_CMDS[cmd](bot, uid, cid, arg.strip())


async def on_callback(bot, q):
    uid, data = q["from"]["id"], q.get("data", "")
    msg = q.get("message") or {}
    cid, mid = msg.get("chat", {}).get("id"), msg.get("message_id")
    if not is_allowed(uid) and not (uid == ADMIN):
        return await bot.answer(q["id"], "دسترسی نداری 🚫")
    kind, _, rest = data.partition(":")
    if kind in ("ok", "no") and uid == ADMIN and rest.isdigit():
        target = int(rest)
        if kind == "ok":
            allow_user(target, "")
            await bot.answer(q["id"], "✅ تأیید شد")
            await bot.edit(cid, mid, f"✅ دسترسی <code>{target}</code> تأیید شد")
            try:
                await bot.send(target, "✅ ادمین دسترسی‌ات رو تأیید کرد. /connect برای وصل کردن اکانت یا /help")
            except Exception:  # noqa
                pass
        else:
            await bot.answer(q["id"], "رد شد")
            await bot.edit(cid, mid, f"❌ درخواست <code>{target}</code> رد شد")
        return
    if data == "go":
        await bot.answer(q["id"])
        await bot.edit(cid, mid, "👍 ادامه...")
        return await ask_phone(bot, uid, cid)
    if data == "dc":
        await bot.answer(q["id"], "در حال حذف...")
        await do_disconnect(uid)
        return await bot.edit(cid, mid, "🗑 اکانتت قطع شد و اطلاعاتت پاک شد. هر وقت خواستی /connect")
    if data == "x":
        await bot.answer(q["id"])
        return await bot.edit(cid, mid, "🔒 بسته شد. /panel برای باز کردن دوباره", {"inline_keyboard": []})
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


async def handle_update(bot, u):
    if "callback_query" in u:
        await on_callback(bot, u["callback_query"])
    elif "message" in u:
        await on_message(bot, u["message"])


async def poll(app):
    while True:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
                bot = Bot(s)
                _bot_ref["bot"] = bot
                me = await bot.api("getMe")
                await bot.api("deleteWebhook")
                log.info("hub bot: @%s admin=%s", me.get("username"), ADMIN)
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
            log.warning("hub bot: %s", e)
            await asyncio.sleep(60 if e.code in (401, 404) else 10)
        except Exception as e:  # noqa
            log.warning("hub bot: %r", e)
            await asyncio.sleep(10)


async def health(request):
    return web.json_response({"hub": True, "running": sum(1 for i in INSTANCES.values() if i.running)})


async def on_startup(app):
    migrate_admin()
    kill_stale()
    app["tasks"] = [asyncio.create_task(poll(app)), asyncio.create_task(start_all()), asyncio.create_task(updater.mark_healthy())]


async def on_cleanup(app):
    for t in app["tasks"]:
        t.cancel()
    await stop_all()


def main():
    configure()
    if not TOKEN or not ADMIN:
        raise SystemExit("HUB_BOT_TOKEN و HUB_ADMIN_ID لازمه")
    app = web.Application()
    app.add_routes([web.get("/", health)])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
