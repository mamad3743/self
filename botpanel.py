"""پنل دکمه‌ای با بات تلگرام (Bot API) — دکمه‌های رنگی با فیلد style.

رنگ‌ها: success = سبز (روشن)، danger = قرمز (خاموش)، primary = آبی (دستوری).
فقط خودِ صاحب سلف می‌تونه از پنل استفاده کنه.
"""
import html
import asyncio

import aiohttp

import core
from core import F, CFG, FEATS, FEAT, GRID, state, save_settings, log

BOT = {"username": None, "running": False}
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
    return {"text": text, "callback_data": data, "style": style}


def feat_style(f) -> str:
    if not f["toggle"]:
        return "primary"
    return "success" if F[f["key"]] else "danger"


def main_text() -> str:
    on = sum(1 for v in F.values() if v)
    return (
        "⚙️ <b>پنل مدیریت سلف</b>\n"
        f"✔ {len(FEATS)} قابلیت آماده استفاده! ({on} روشن)\n"
        "🟢 روشن   🔴 خاموش   🔵 دستوری\n\n"
        "روی هر دکمه بزن تا راهنما و نمونه دستور رو ببینی."
    )


def main_keyboard() -> dict:
    rows = []
    for row in GRID:
        btns = [
            btn(f"{FEAT[k]['emoji']} {FEAT[k]['name']}", f"f:{k}", feat_style(FEAT[k]))
            for k in row
        ]
        rows.append(list(reversed(btns)))  # ردیف‌ها از راست به چپ
    return {"inline_keyboard": rows}


def feat_text(key) -> str:
    f = FEAT[key]
    status = ("🟢 روشن" if F[key] else "🔴 خاموش") if f["toggle"] else "🔵 دستوری"
    ex = "\n".join(f"<code>{html.escape(e)}</code>" for e in f["examples"])
    return (
        f"{f['emoji']} <b>{html.escape(f['name'])}</b>\n"
        f"وضعیت: {status}\n\n{html.escape(f['desc'])}\n\n<b>نمونه:</b>\n{ex}"
    )


def feat_keyboard(key) -> dict:
    rows = []
    if FEAT[key]["toggle"]:
        rows.append([btn("🔴 خاموش", f"t:{key}:0", "danger"), btn("🟢 روشن", f"t:{key}:1", "success")])
    rows.append([btn("🔙 بازگشت", "m", "primary")])
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
    if data == "m":
        return main_text(), main_keyboard(), None
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
async def handle(session, token, update):
    me = state.get("me")
    if "callback_query" in update:
        q = update["callback_query"]
        if not me or q["from"]["id"] != me:
            await call(session, token, "answerCallbackQuery", callback_query_id=q["id"],
                       text="این پنل خصوصیه", show_alert=True)
            return
        text, kb, toast = await route(q.get("data", ""))
        await call(session, token, "answerCallbackQuery", callback_query_id=q["id"], text=toast)
        msg = q.get("message") or {}
        if not msg:
            return
        try:
            await call(session, token, "editMessageText", chat_id=msg["chat"]["id"],
                       message_id=msg["message_id"], text=text, parse_mode="HTML",
                       reply_markup=kb, link_preview_options={"is_disabled": True})
        except BotError as e:
            if "not modified" not in str(e):
                raise
    elif "message" in update:
        msg = update["message"]
        if me and msg.get("from", {}).get("id") == me:  # بقیه نادیده گرفته می‌شن
            await call(session, token, "sendMessage", chat_id=msg["chat"]["id"],
                       text=main_text(), parse_mode="HTML", reply_markup=main_keyboard())


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
                BOT.update(username=me.get("username"), running=True)
                await call(s, token, "deleteWebhook")
                log.info("bot panel: @%s", BOT["username"])
                offset = None
                while CFG["bot_token"] == token:
                    ups = await call(s, token, "getUpdates", offset=offset, timeout=25,
                                     allowed_updates=["message", "callback_query"])
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
