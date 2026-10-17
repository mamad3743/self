"""پنل دکمه‌ای با بات تلگرام (Bot API) — دکمه‌های رنگی با فیلد style.

رنگ‌ها: success = سبز (روشن)، danger = قرمز (خاموش)، primary = آبی (دستوری).
فقط خودِ صاحب سلف می‌تونه از پنل استفاده کنه؛ بقیه پیام «این پنل برای شما نیست» می‌گیرن.
حالت اینلاین: با .پنل توی هر چتی پنل ارسال می‌شه (باید inline mode بات توی BotFather روشن باشه).
"""
import html
import os
import asyncio

import aiohttp

import core
import miniapp
from core import F, CFG, FEATS, FEAT, GRID, state, save_settings, log

BOT = {"username": None, "running": False, "id": None}
API_URL = "https://api.telegram.org/bot{token}/{method}"


class BotError(Exception):
    def __init__(self, description, code=None):
        super().__init__(description)
        self.code = code


async def call(session, token, method, **params):
    params = {k: v for k, v in params.items() if v is not None}
    async with session.post(API_URL.format(token=token, method=method), json=params) as r:
        data = await r.json(content_type=None)
    if not data.get("ok"):
        raise BotError(data.get("description", "?"), data.get("error_code"))
    return data["result"]


# ───────────── صفحه‌ها ─────────────
def btn(text, data, style):
    """رنگ دکمه بر اساس تم: classic = رنگ‌های معنایی، mono = همه آبی، plain = بدون رنگ."""
    b = {"text": text, "callback_data": data}
    theme = CFG.get("theme", "classic")
    if theme == "classic":
        b["style"] = style
    elif theme == "mono":
        b["style"] = "primary"
    return b


def feat_style(f) -> str:
    if not f["toggle"]:
        return "primary"
    return "success" if F[f["key"]] else "danger"


def _uptime() -> str:
    try:
        s = int(__import__("time").time() - core.START_TIME)
    except Exception:  # noqa
        return ""
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    parts = []
    if d:
        parts.append(f"{d} روز")
    if h:
        parts.append(f"{h} ساعت")
    parts.append(f"{m} دقیقه")
    return " و ".join(parts)


def main_text() -> str:
    on = sum(1 for v in F.values() if v)
    up = _uptime()
    clk = "🕐 ساعت روشن" if F.get("clock") else "🕐 ساعت خاموش"
    dt = "📅 تاریخ روشن" if F.get("date") else "📅 تاریخ خاموش"
    return (
        "🔥 <b>پنل مدیریت سلف</b>\n"
        f"🤖 ⏱ {up} · 🎛 <b>{on}</b> از {len(FEATS)} روشن\n"
        f"{clk} · {dt}\n"
        "🟢 روشن · 🔴 خاموش · 🔵 دستوری\n\n"
        "👇 دکمه‌ی هر قابلیت = راهنما + نمونه دستور + روشن/خاموش"
    )


def start_link() -> str:
    """لینک باز کردن چت بات با پارامتر app (بات توش دکمه‌ی مینی‌اپ می‌فرسته)."""
    return f"https://t.me/{BOT['username']}?start=app" if BOT.get("username") else ""


def miniapp_link() -> str:
    """لینک باز کردن مینی‌اپ از هر چت (دکمه‌ی url).
    اگه Main Mini App توی BotFather تنظیم شده باشه، ?startapp مینی‌اپ رو همون‌جا باز می‌کنه (بدون رفتن توی چت بات)؛
    وگرنه ?start=app. با متغیر MINIAPP_LINK می‌تونی لینک دلخواه (مثلاً t.me/بات/اسم‌اپ) بذاری."""
    custom = (os.getenv("MINIAPP_LINK") or "").strip()
    if custom:
        return custom
    u = BOT.get("username")
    if not u:
        return ""
    return f"https://t.me/{u}?startapp" if BOT.get("main_app") else f"https://t.me/{u}?start=app"


def app_available() -> bool:
    try:
        return bool(miniapp.app_url()) or bool(BOT.get("main_app")) or bool((os.getenv("MINIAPP_LINK") or "").strip())
    except Exception:  # noqa
        return False


def app_row(inline: bool = False):
    """دکمه‌ی مینی‌اپ.
    ⚠️ تلگرام دکمه‌ی web_app رو فقط توی چت خصوصی با خود بات قبول می‌کنه؛ توی نتیجه‌ی inline یا پیام inline
    خطای BUTTON_TYPE_INVALID می‌ده. برای inline لینک t.me می‌ذاریم."""
    if not app_available():
        return None
    try:
        u = miniapp.app_url()
    except Exception:  # noqa
        u = ""
    if inline or not u:
        link = miniapp_link()
        return [{"text": "📱 مینی‌اپ", "url": link}] if link else None
    return [{"text": "📱 مینی‌اپ", "web_app": {"url": u}}]


def strip_web_app(kb):
    """هر دکمه‌ی web_app رو به لینک t.me تبدیل می‌کنه (یا حذف) تا برای پیام inline معتبر باشه."""
    if not isinstance(kb, dict):
        return kb
    link = miniapp_link()
    rows = []
    for row in kb.get("inline_keyboard", []):
        new = []
        for b in row:
            if "web_app" in b:
                if link:
                    new.append({"text": b["text"], "url": link})
            else:
                new.append(b)
        if new:
            rows.append(new)
    return {"inline_keyboard": rows}


def _bullets(items) -> str:
    return "\n".join(f"• {x}" for x in items) if items else "—"


def menu_text() -> str:
    on = sum(1 for k, v in F.items() if v and k in FEAT and FEAT[k]["toggle"])
    total = sum(1 for f in FEATS if f["toggle"])
    t = f"⚙️ <b>پنل سلف</b>\n⏱ {_uptime()} · 🎛 <b>{on}</b> از {total} قابلیت روشن"
    if not (app_available() or miniapp.web_url()):
        t += ("\n\nℹ️ برای دکمه‌ی مینی‌اپ و پنل وب، توی Railway دامنه‌ی عمومی بساز "
              "(یا متغیر <b>HUB_DOMAIN</b> رو بذار).")
    return t


def menu_keyboard(inline: bool = False) -> dict:
    """منوی کوچیک .پنل: مینی‌اپ، وضعیت، بازی‌ها، «پنل تحت وب» (پایین)، بستن."""
    rows = []
    r = app_row(inline)
    if r:
        rows.append(r)
    rows.append([btn("📊 وضعیت", "st", "primary"), btn("🎮 بازی‌ها", "gm", "primary")])
    try:
        w = miniapp.web_url()
    except Exception:  # noqa
        w = ""
    if w:
        rows.append([{"text": "🌐 پنل تحت وب", "url": w}])
    rows.append([btn("❌ بستن", "x", "danger")])
    return {"inline_keyboard": rows}


def back_keyboard() -> dict:
    return {"inline_keyboard": [[btn("🔙 منو", "mu", "primary"), btn("❌ بستن", "x", "danger")]]}


def status_view() -> str:
    on = [f"{FEAT[k]['emoji']} {FEAT[k]['name']}" for k, v in F.items() if v and k in FEAT and FEAT[k]["toggle"]]
    return (f"📊 <b>وضعیت سلف</b>\n⏱ مدت اجرا: {_uptime()}\n"
            f"🔐 اکانت: {'وصل ✅' if core.state.get('authorized') else 'وصل نیست ❌'}\n\n"
            f"🎛 <b>قابلیت‌های روشن ({len(on)})</b>\n{_bullets(on)}")


def games_view() -> str:
    """حلقه‌های بازی میویی که الان فعالن و زمان نوبت بعدی هر کدوم."""
    try:
        import meow
        tasks = sorted(meow.TASKS)
        names = meow.KIND_NAME
        now = __import__("time").time()
        rows = []
        for kind, cid in tasks:
            nxt = meow.next_get(kind, cid) - now
            when = f"{int(nxt // 60)} دقیقه و {int(nxt % 60)} ثانیه دیگه" if nxt > 5 else "الان / به‌زودی"
            rows.append(f"{names.get(kind, kind)} · چت <code>{cid}</code> · نوبت بعدی: {when}")
    except Exception as e:  # noqa
        return f"🎮 <b>بازی‌ها</b>\n\nخطا: {e}"
    return "🎮 <b>بازی‌های فعال</b>\n\n" + (_bullets(rows) if rows else "هیچ بازی‌ای روشن نیست.\nتوی چت میویی: <code>.بازی روشن</code>")


def main_keyboard(inline: bool = False) -> dict:
    rows = []
    r = app_row(inline)
    if r:
        rows.append(r)
    rows.append([btn("📊 وضعیت سلف", "f:status", "primary"), btn("💾 پشتیبان", "f:backup", "primary"),
                 btn("🐱 بازی", "f:automeow", "primary")])
    for row in GRID:
        btns = [
            btn(f"{FEAT[k]['emoji']} {FEAT[k]['name']}", f"f:{k}", feat_style(FEAT[k]))
            for k in row
        ]
        rows.append(list(reversed(btns)))  # ردیف‌ها از راست به چپ
    rows.append([btn("❌ بستن پنل", "x", "danger")])
    return {"inline_keyboard": rows}


def feat_text(key) -> str:
    f = FEAT[key]
    on = sum(1 for v in F.values() if v)
    if f["toggle"]:
        status = ("🟢 <b>روشنه</b> — با دکمه‌ی زیر خاموشش کن" if F[key]
                  else "🔴 <b>خاموشه</b> — با دکمه‌ی زیر روشنش کن")
    else:
        status = "🔵 دستوری — با دستور اجراش کن"
    ex = "\n".join(f"<code>{html.escape(e)}</code>" for e in f["examples"])
    return (
        f"{f['emoji']} <b>{html.escape(f['name'])}</b>\n"
        f"{status}\n"
        f"🎛 {on} قابلیت روشنه\n\n"
        f"📖 {html.escape(f['desc'])}\n\n"
        f"⌨️ <b>نمونه دستور:</b>\n{ex}"
    )


def feat_keyboard(key) -> dict:
    rows = []
    if FEAT[key]["toggle"]:
        rows.append([btn("🔴 خاموش", f"t:{key}:0", "danger"), btn("🟢 روشن", f"t:{key}:1", "success")])
    rows.append([btn("🔙 بازگشت", "m", "primary"), btn("❌ بستن", "x", "danger")])
    return {"inline_keyboard": rows}


async def toggle(key, value):
    if key not in F:
        return
    F[key] = value
    save_settings()
    if key in ("clock", "date") and "refresh" in core.hooks:
        await core.hooks["refresh"]()


async def route(data):
    """(متن، کیبورد، پیام کوتاه) برای هر دکمه."""
    if data == "mu":
        return menu_text(), menu_keyboard(), None
    if data == "st":
        return status_view(), back_keyboard(), None
    if data == "gm":
        return games_view(), back_keyboard(), None
    if data == "m":
        return main_text(), main_keyboard(), None
    if data == "x":
        return "🔒 پنل بسته شد. برای باز کردن دوباره: <code>.پنل</code>", {"inline_keyboard": []}, None
    kind, _, rest = data.partition(":")
    if kind == "f" and rest in FEAT:
        return feat_text(rest), feat_keyboard(rest), None
    if kind == "t":
        key, _, v = rest.partition(":")
        if key in FEAT:
            await toggle(key, v == "1")
            return feat_text(key), feat_keyboard(key), "✅ انجام شد"
    return main_text(), main_keyboard(), None


# ───────────── پردازش آپدیت‌ها ─────────────
NOT_YOURS = "این پنل برای شما نیست 🚫"


def is_owner(user_id) -> bool:
    me = state.get("me")
    return bool(me) and user_id == me


async def handle(session, token, update):
    if "inline_query" in update:
        q = update["inline_query"]
        results = []
        if is_owner(q["from"]["id"]):
            results = [{
                "type": "article",
                "id": "panel",
                "title": "⚙️ پنل سلف",
                "description": "مینی‌اپ · وضعیت · بازی‌ها · پنل تحت وب",
                "input_message_content": {"message_text": menu_text(), "parse_mode": "HTML"},
                "reply_markup": menu_keyboard(inline=True),  # بدون web_app (توی inline نامعتبره)
            }]
        try:
            await call(session, token, "answerInlineQuery", inline_query_id=q["id"],
                       results=results, cache_time=0, is_personal=True)
        except BotError as e:  # هرچی تلگرام نپذیرفت، حداقل پنل ساده جواب داده می‌شه (نه خالی ← جایگزین توی بات)
            log.warning("inline answer failed (%s); retry without extras", e)
            for r in results:
                r["reply_markup"] = strip_web_app(r.get("reply_markup"))
            await call(session, token, "answerInlineQuery", inline_query_id=q["id"],
                       results=results[:1], cache_time=0, is_personal=True)

    elif "callback_query" in update:
        q = update["callback_query"]
        if not is_owner(q["from"]["id"]):  # هر کس غیر از خودت
            await call(session, token, "answerCallbackQuery", callback_query_id=q["id"],
                       text=NOT_YOURS, show_alert=True)
            return
        text, kb, toast = await route(q.get("data", ""))
        await call(session, token, "answerCallbackQuery", callback_query_id=q["id"], text=toast)
        where = {}
        if q.get("inline_message_id"):  # پنلی که توی چت دیگه‌ای فرستاده شده
            where = {"inline_message_id": q["inline_message_id"]}
            kb = strip_web_app(kb)  # web_app توی پیام inline نامعتبره (BUTTON_TYPE_INVALID)
        elif q.get("message"):
            where = {"chat_id": q["message"]["chat"]["id"], "message_id": q["message"]["message_id"]}
        else:
            return
        try:
            await call(session, token, "editMessageText", text=text, parse_mode="HTML",
                       reply_markup=kb, link_preview_options={"is_disabled": True}, **where)
        except BotError as e:
            if "not modified" not in str(e):
                raise

    elif "message" in update:
        msg = update["message"]
        if is_owner(msg.get("from", {}).get("id")):  # بقیه نادیده گرفته می‌شن
            text = (msg.get("text") or "").strip().lower()
            if text == "/classic":  # پنل قدیمیِ دکمه‌ای (مخفی؛ توی منوی جدید نیست)
                await call(session, token, "sendMessage", chat_id=msg["chat"]["id"],
                           text=main_text(), parse_mode="HTML", reply_markup=main_keyboard())
            else:  # منوی کوچیک: مینی‌اپ، وضعیت، بازی‌ها، پنل تحت وب
                await call(session, token, "sendMessage", chat_id=msg["chat"]["id"],
                           text=menu_text(), parse_mode="HTML", reply_markup=menu_keyboard())


async def send_panel() -> str:
    """پنل رو برای خودت می‌فرسته. خروجی: ok | no_token | not_started | no_me | متن خطا"""
    token, me = CFG["bot_token"], state.get("me")
    if not token:
        return "no_token"
    if not me:
        return "no_me"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
            await call(s, token, "sendMessage", chat_id=me, text=main_text(),
                       parse_mode="HTML", reply_markup=main_keyboard())
        return "ok"
    except BotError as e:
        if e.code == 403:
            return "not_started"
        return str(e)
    except Exception as e:  # noqa
        return str(e)


async def discover_menu_url(session, token):
    """اگه دامنه از متغیرها معلوم نیست، آدرس مینی‌اپ رو از دکمه‌ی منوی WebApp که توی BotFather تنظیم شده می‌خونیم؛
    اگه دامنه معلومه و دکمه‌ی منو هنوز WebApp نیست، خودمون ستش می‌کنیم (دکمه‌ی 📱 کنار باکس پیام)."""
    try:
        mb = await call(session, token, "getChatMenuButton")
    except Exception as e:  # noqa
        log.info("getChatMenuButton failed: %s", e)
        return
    cur = (mb or {}).get("web_app", {}).get("url", "") if (mb or {}).get("type") == "web_app" else ""
    if cur and not (miniapp.domain()):
        miniapp.LEARNED["menu_url"] = cur
        log.info("mini-app url from BotFather menu button: %s", cur)
    if not cur and miniapp.domain():
        try:
            await call(session, token, "setChatMenuButton",
                       menu_button={"type": "web_app", "text": "📱 مینی‌اپ", "web_app": {"url": miniapp.app_url()}})
        except Exception as e:  # noqa
            log.info("setChatMenuButton failed: %s", e)


async def run():
    """حلقه‌ی دریافت آپدیت‌های بات (long polling)."""
    while True:
        token = CFG["bot_token"]
        if not token:
            BOT["running"] = False
            await asyncio.sleep(5)
            continue
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as s:
                me = await call(s, token, "getMe")
                BOT.update(username=me.get("username"), running=True, id=me.get("id"), main_app=bool(me.get("has_main_web_app")))
                await call(s, token, "deleteWebhook")
                await discover_menu_url(s, token)
                log.info("bot panel: @%s", BOT["username"])
                offset = None
                while CFG["bot_token"] == token:
                    ups = await call(s, token, "getUpdates", offset=offset, timeout=25,
                                     allowed_updates=["message", "callback_query", "inline_query"])
                    for u in ups:
                        offset = u["update_id"] + 1
                        try:
                            await handle(s, token, u)
                        except Exception as e:  # noqa
                            log.warning("bot update failed: %s", e)
        except asyncio.CancelledError:
            raise
        except BotError as e:
            BOT["running"] = False
            log.warning("bot: %s", e)
            await asyncio.sleep(60 if e.code in (401, 404) else 10)
        except Exception as e:  # noqa
            BOT["running"] = False
            log.warning("bot: %s", e)
            await asyncio.sleep(10)
