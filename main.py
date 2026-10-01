import os
import re
import ast
import json
import time
import operator
import hmac
import html
import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    FloodWaitError,
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    ApiIdInvalidError,
)
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("self")

API_FILE = os.getenv("API_FILE", "/data/api.json")
API = {"id": int(os.getenv("API_ID") or 0), "hash": os.getenv("API_HASH", "")}
PANEL_PASSWORD = os.environ["PANEL_PASSWORD"]  # رمز ورود به پنل وب
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tehran"))
SESSION_FILE = os.getenv("SESSION_FILE", "/data/session.txt")
PORT = int(os.getenv("PORT", "8080"))
TOKEN = hmac.new(PANEL_PASSWORD.encode(), b"panel", hashlib.sha256).hexdigest()

FONTS = {
    "1": str.maketrans("0123456789", "0123456789"),
    "2": str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"),
    "3": str.maketrans("0123456789", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"),
    "4": str.maketrans("0123456789", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿"),
    "5": str.maketrans("0123456789", "⓪①②③④⑤⑥⑦⑧⑨"),
}
DIGITS = r"[0-9۰-۹𝟎-𝟗𝟶-𝟿⓪①②③④⑤⑥⑦⑧⑨]"
EMOJIS = "⏰⌚🕐🕑🕒🕓🕔🕕🕖🕗🕘🕙🕚🕛"
CLOCK_RE = re.compile(rf"\s*[{EMOJIS}]?\s*{DIGITS}{{1,2}}\s*:\s*{DIGITS}{{1,2}}\s*$")

state = {
    "enabled": True,
    "target": os.getenv("CLOCK_TARGET", "last_name"),
    "font": os.getenv("CLOCK_FONT", "2"),
    "emoji": os.getenv("CLOCK_EMOJI", ""),  # خالی = بدون ایموجی
    "afk": None,
    "afk_seen": {},
    "last_text": None,
    "authorized": False,
    "step": "phone",  # phone | code | 2fa
    "phone": None,
    "hash": None,
}
client: TelegramClient = None


# ───────────── session ─────────────
def load_session() -> str:
    try:
        with open(SESSION_FILE) as f:
            return f.read().strip()
    except OSError:
        return os.getenv("SESSION_STRING", "")


def save_session():
    try:
        os.makedirs(os.path.dirname(SESSION_FILE) or ".", exist_ok=True)
        with open(SESSION_FILE, "w") as f:
            f.write(client.session.save())
    except OSError as e:
        log.warning("نمی‌تونم سشن رو ذخیره کنم (Volume نذاشتی؟): %s", e)


def load_api():
    if API["id"] and API["hash"]:
        return
    try:
        with open(API_FILE) as f:
            d = json.load(f)
        API.update(id=int(d["id"]), hash=d["hash"])
    except (OSError, ValueError, KeyError):
        pass


def save_api():
    try:
        os.makedirs(os.path.dirname(API_FILE) or ".", exist_ok=True)
        with open(API_FILE, "w") as f:
            json.dump(API, f)
    except OSError as e:
        log.warning("نمی‌تونم API رو ذخیره کنم: %s", e)


def make_client(session: str = "") -> TelegramClient:
    c = TelegramClient(StringSession(session), API["id"], API["hash"])
    c.add_event_handler(
        commands,
        events.NewMessage(
            outgoing=True,
            pattern=r"(?s)^\.(clock|ping|help|id|afk|del|type|calc|time)(?:\s+(.*))?$",
        ),
    )
    c.add_event_handler(
        afk_reply, events.NewMessage(incoming=True, func=lambda e: e.is_private)
    )
    return c


# ───────────── clock ─────────────
def clock_text() -> str:
    t = f"{datetime.now(TZ):%H:%M}".translate(FONTS.get(state["font"], FONTS["1"]))
    return f"{state['emoji']} {t}".strip()


def strip_clock(s: str) -> str:
    return CLOCK_RE.sub("", s or "").strip()


async def get_bases():
    me = await client.get_me()
    full = await client(GetFullUserRequest(me))
    return strip_clock(me.last_name or ""), strip_clock(full.full_user.about or "")


async def apply(clock: bool):
    base_last, base_bio = await get_bases()
    text = clock_text() if clock else ""
    try:
        if state["target"] == "bio":
            await client(UpdateProfileRequest(about=f"{base_bio} {text}".strip()[:70]))
            if not clock:
                await client(UpdateProfileRequest(last_name=base_last))
        else:
            await client(UpdateProfileRequest(last_name=f"{base_last} {text}".strip()[:64]))
            if not clock:
                await client(UpdateProfileRequest(about=base_bio))
    except FloodWaitError as e:
        log.warning("FloodWait %ss", e.seconds)
        await asyncio.sleep(e.seconds + 1)


async def clock_loop():
    while True:
        try:
            if state["enabled"] and state["authorized"]:
                t = clock_text()
                if t != state["last_text"]:
                    await apply(True)
                    state["last_text"] = t
        except Exception as e:  # noqa
            log.exception("clock error: %s", e)
        now = datetime.now(TZ)
        nxt = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        await asyncio.sleep(max((nxt - now).total_seconds(), 1))


HELP = (
    "دستورات:\n"
    ".clock on | off | name | bio\n"
    ".clock font 1-5\n"
    ".clock emoji ⏰   (یا: .clock emoji off)\n"
    ".ping\n.time\n.id (روی ریپلای = آیدی طرف)\n"
    ".afk [دلیل]  /  .afk off\n"
    ".del [تعداد]  (پیام‌های خودت رو پاک می‌کنه)\n"
    ".type متن\n.calc 2*(3+4)"
)

OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg,
}


def safe_calc(expr: str):
    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 100:
                raise ValueError("توان زیاد")
            return OPS[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.operand))
        raise ValueError("عبارت نامعتبر")
    return ev(ast.parse(expr, mode="eval").body)


async def safe_edit(event, text):
    try:
        await event.edit(text)
    except Exception:  # noqa
        pass


async def commands(event):
    cmd = event.pattern_match.group(1)
    arg = (event.pattern_match.group(2) or "").strip()

    if cmd == "ping":
        t0 = time.perf_counter()
        await event.edit("...")
        await event.edit(f"pong 🏓 {int((time.perf_counter() - t0) * 1000)}ms")

    elif cmd == "help":
        await event.edit(HELP)

    elif cmd == "time":
        await event.edit(f"🕒 {datetime.now(TZ):%Y-%m-%d  %H:%M:%S}")

    elif cmd == "id":
        if event.is_reply:
            r = await event.get_reply_message()
            await event.edit(f"user: `{r.sender_id}`\nchat: `{event.chat_id}`")
        else:
            await event.edit(f"chat: `{event.chat_id}`")

    elif cmd == "afk":
        if arg == "off":
            state["afk"] = None
            await event.edit("برگشتم ✅")
        else:
            state["afk"], state["afk_seen"] = arg or "الان آفلاینم، بعداً جواب می‌دم", {}
            await event.edit("حالت AFK روشن شد 🌙")

    elif cmd == "del":
        n = min(int(arg) if arg.isdigit() else 1, 100)
        msgs = [m async for m in client.iter_messages(event.chat_id, from_user="me", limit=n + 1)]
        await client.delete_messages(event.chat_id, msgs)

    elif cmd == "type":
        if not arg:
            return
        out = ""
        for w in arg.split(" ")[:40]:
            out = f"{out} {w}".strip()
            await safe_edit(event, out + " ▌")
            await asyncio.sleep(0.4)
        await safe_edit(event, out)

    elif cmd == "calc":
        try:
            await event.edit(f"{arg} = {safe_calc(arg)}")
        except ZeroDivisionError:
            await event.edit("تقسیم بر صفر 😅")
        except Exception:  # noqa
            await event.edit("عبارت نامعتبره")

    elif cmd == "clock":
        if arg == "on":
            state["enabled"], state["last_text"] = True, None
            await event.edit("ساعت روشن شد ✅")
        elif arg == "off":
            state["enabled"] = False
            await apply(False)
            await event.edit("ساعت خاموش شد ❌")
        elif arg in ("name", "bio"):
            await apply(False)
            state["target"] = "bio" if arg == "bio" else "last_name"
            state["last_text"] = None
            await event.edit("انجام شد ✅")
        elif arg.startswith("font") and arg.split()[-1] in FONTS:
            state["font"], state["last_text"] = arg.split()[-1], None
            await event.edit("فونت عوض شد ✅")
        elif arg.startswith("emoji"):
            e = arg[5:].strip()
            await apply(False)
            state["emoji"] = "" if e in ("", "off", "none") else e[:2]
            state["last_text"] = None
            await event.edit("ایموجی عوض شد ✅")
        else:
            await event.edit(HELP)


async def afk_reply(event):
    if not state["afk"] or not state["authorized"]:
        return
    sender = await event.get_sender()
    if getattr(sender, "bot", False):
        return
    now = time.time()
    if now - state["afk_seen"].get(event.sender_id, 0) < 900:  # هر ۱۵ دقیقه یه بار
        return
    state["afk_seen"][event.sender_id] = now
    await event.reply(f"🌙 {state['afk']}")


# ───────────── web panel ─────────────
TEMPLATE = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>پنل سلف</title>
<style>
body{font-family:system-ui,Tahoma,sans-serif;background:#0f1419;color:#e7e9ea;display:flex;
justify-content:center;padding:24px}
.card{background:#1a2129;border-radius:14px;padding:24px;width:100%;max-width:380px}
h2{margin-top:0}input,select,button{width:100%;padding:12px;margin:6px 0;border-radius:8px;
border:1px solid #2f3b47;background:#0f1419;color:#e7e9ea;font-size:16px;box-sizing:border-box}
button{background:#2a9df4;border:0;font-weight:bold;cursor:pointer}
button.red{background:#e0245e}.msg{background:#3b2a2a;padding:10px;border-radius:8px}
.ok{background:#1f3b2a}small{color:#8b98a5}
</style></head><body><div class="card">{{BODY}}</div></body></html>"""


def page(body: str, msg: str = "", ok: bool = False) -> web.Response:
    m = f'<p class="msg {"ok" if ok else ""}">{html.escape(msg)}</p>' if msg else ""
    return web.Response(
        text=TEMPLATE.replace("{{BODY}}", m + body), content_type="text/html"
    )


def authed(request) -> bool:
    return hmac.compare_digest(request.cookies.get("auth", "").encode(), TOKEN.encode())


F_PANEL = """<h2>🔐 ورود به پنل</h2><form method="post" action="/panel">
<input type="password" name="password" placeholder="رمز پنل" required><button>ورود</button></form>"""

F_API = """<h2>⚙️ اطلاعات API</h2><form method="post" action="/api">
<input name="api_id" placeholder="API ID (عدد)" dir="ltr" inputmode="numeric" required>
<input name="api_hash" placeholder="API Hash" dir="ltr" required>
<button>ذخیره و ادامه</button></form><small>از my.telegram.org ← API development tools</small>"""

F_PHONE = """<h2>📱 ورود به تلگرام</h2><form method="post" action="/phone">
<input name="phone" placeholder="+989123456789" dir="ltr" required>
<button>ارسال کد</button></form><small>شماره با کد کشور، مثلا +98...</small>"""

F_CODE = """<h2>💬 کد تایید</h2><form method="post" action="/code">
<input name="code" placeholder="کد ۵ رقمی" dir="ltr" inputmode="numeric" required>
<button>تایید</button></form><small>کد داخل خود تلگرام (چت Telegram) برات میاد.</small>"""

F_2FA = """<h2>🔑 رمز دو مرحله‌ای</h2><form method="post" action="/2fa">
<input type="password" name="password" placeholder="رمز تایید دو مرحله‌ای" required>
<button>ورود</button></form>"""


async def status_page(msg="", ok=False):
    me = await client.get_me()
    sel = lambda v, cur: "selected" if v == cur else ""  # noqa
    body = f"""<h2>✅ وصل شدی</h2><p>{html.escape(me.first_name or '')} 
<small dir="ltr">@{html.escape(me.username or '-')}</small></p>
<form method="post" action="/settings">
<select name="enabled"><option value="1" {sel('1', '1' if state['enabled'] else '0')}>ساعت روشن</option>
<option value="0" {sel('0', '1' if state['enabled'] else '0')}>ساعت خاموش</option></select>
<select name="target"><option value="last_name" {sel('last_name', state['target'])}>نمایش در فامیلی</option>
<option value="bio" {sel('bio', state['target'])}>نمایش در بیو</option></select>
<select name="emoji">{''.join(f'<option value="{e}" {sel(e, state["emoji"])}>{e or "بدون ایموجی"}</option>' for e in ["", "⏰", "🕒", "⌚"])}</select>
<select name="font">{''.join(f'<option value="{k}" {sel(k, state["font"])}>فونت {k}: {("12:34").translate(v)}</option>' for k, v in FONTS.items())}</select>
<button>ذخیره</button></form>
<form method="post" action="/logout"><button class="red">خروج از اکانت</button></form>"""
    return page(body, msg, ok)


async def index(request):
    if not authed(request):
        return page(F_PANEL)
    if client is None:
        return page(F_API)
    if state["authorized"]:
        return await status_page()
    return page({"phone": F_PHONE, "code": F_CODE, "2fa": F_2FA}[state["step"]])


async def panel_login(request):
    data = await request.post()
    if hmac.compare_digest(data.get("password", "").encode(), PANEL_PASSWORD.encode()):
        resp = web.HTTPFound("/")
        resp.set_cookie("auth", TOKEN, httponly=True, secure=True, max_age=86400 * 30)
        raise resp
    await asyncio.sleep(1.5)
    return page(F_PANEL, "رمز اشتباهه")


def need_auth(handler):
    async def wrapper(request):
        if not authed(request):
            raise web.HTTPFound("/")
        return await handler(request)
    return wrapper


@need_auth
async def send_api(request):
    global client
    data = await request.post()
    try:
        api_id = int(data["api_id"].strip())
    except ValueError:
        return page(F_API, "API ID باید عدد باشه")
    API.update(id=api_id, hash=data["api_hash"].strip())
    save_api()
    client = make_client()
    await client.connect()
    state.update(authorized=False, step="phone")
    raise web.HTTPFound("/")


@need_auth
async def send_phone(request):
    global client
    data = await request.post()
    phone = data["phone"].strip().replace(" ", "")
    try:
        sent = await client.send_code_request(phone)
    except ApiIdInvalidError:
        await client.disconnect()
        client = None
        API.update(id=0, hash="")
        try:
            os.remove(API_FILE)
        except OSError:
            pass
        return page(F_API, "API ID یا API Hash اشتباهه، دوباره وارد کن")
    except Exception as e:  # noqa
        return page(F_PHONE, f"خطا: {e}")
    state.update(phone=phone, hash=sent.phone_code_hash, step="code")
    raise web.HTTPFound("/")


async def finish_login():
    save_session()
    state.update(authorized=True, step="phone", last_text=None)
    log.info("Login OK")


@need_auth
async def send_code(request):
    data = await request.post()
    code = data["code"].strip().replace(" ", "")
    try:
        await client.sign_in(state["phone"], code, phone_code_hash=state["hash"])
    except SessionPasswordNeededError:
        state["step"] = "2fa"
        raise web.HTTPFound("/")
    except PhoneCodeInvalidError:
        return page(F_CODE, "کد اشتباهه")
    except PhoneCodeExpiredError:
        state["step"] = "phone"
        return page(F_PHONE, "کد منقضی شد، دوباره شماره بزن")
    except Exception as e:  # noqa
        return page(F_CODE, f"خطا: {e}")
    await finish_login()
    raise web.HTTPFound("/")


@need_auth
async def send_2fa(request):
    data = await request.post()
    try:
        await client.sign_in(password=data["password"])
    except PasswordHashInvalidError:
        return page(F_2FA, "رمز اشتباهه")
    except Exception as e:  # noqa
        return page(F_2FA, f"خطا: {e}")
    await finish_login()
    raise web.HTTPFound("/")


@need_auth
async def settings(request):
    data = await request.post()
    was_on = state["enabled"]
    if state["authorized"]:
        await apply(False)  # پاک کردن ساعت قبلی از محل قبلی
    state["enabled"] = data.get("enabled") == "1"
    state["target"] = data.get("target", "last_name")
    state["font"] = data.get("font", "2")
    state["emoji"] = data.get("emoji", "")
    state["last_text"] = None
    if state["enabled"]:
        await apply(True)
        state["last_text"] = clock_text()
    return await status_page("ذخیره شد", ok=True)


@need_auth
async def logout(request):
    global client
    try:
        await apply(False)
        await client.log_out()
    except Exception as e:  # noqa
        log.warning("logout: %s", e)
    try:
        os.remove(SESSION_FILE)
    except OSError:
        pass
    client = make_client()
    await client.connect()
    state.update(authorized=False, step="phone")
    raise web.HTTPFound("/")


async def on_startup(app):
    global client
    load_api()
    if API["id"] and API["hash"]:
        client = make_client(load_session())
        await client.connect()
        state["authorized"] = await client.is_user_authorized()
    log.info("authorized=%s", state["authorized"])
    app["clock"] = asyncio.create_task(clock_loop())


async def on_cleanup(app):
    app["clock"].cancel()
    if client:
        await client.disconnect()


def main():
    app = web.Application()
    app.add_routes([
        web.get("/", index),
        web.post("/panel", panel_login),
        web.post("/api", send_api),
        web.post("/phone", send_phone),
        web.post("/code", send_code),
        web.post("/2fa", send_2fa),
        web.post("/settings", settings),
        web.post("/logout", logout),
    ])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
