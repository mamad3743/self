"""همه‌ی دستورها و رویدادهای سلف."""
import os
import re
import io
import random
import ast
import json
import time
import socket
import asyncio
import tempfile
import ipaddress
import operator
import urllib.parse
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timedelta

import aiohttp
from telethon import TelegramClient, events, utils, Button
from telethon.sessions import StringSession
from telethon.tl import types
from telethon.errors import FloodWaitError, UserNotParticipantError
from telethon.tl.functions.account import UpdateProfileRequest, UpdateStatusRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.functions.messages import SendReactionRequest, SetTypingRequest

import core
import botpanel
import meow
import updater
import ctl
import extras
import miniapp
from core import (
    F, CFG, FEATS, FEAT, state, log, TZ, save_settings, digits,
    jalali_short, jalali_long, clock_text, strip_clock, strip_bio, profile_key,
)

cooldown = {}
cache = OrderedDict()  # پیام‌های دریافتی پی‌وی برای ضد حذف
action_tasks = {}
FA2EN = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
SKIP_PREFIXES = (".", "🌙", "🗑", "✏️", "🔔", "⚙️", "📖", "🤖", "📅", "🛡", "🩺", "🔄")


def C():
    return core.client


# ───────────── ابزارهای کمکی ─────────────
def dname(s) -> str:
    n = " ".join(x for x in [getattr(s, "first_name", None), getattr(s, "last_name", None)] if x)
    return n or getattr(s, "title", None) or "ناشناس"


def cooled(key, secs) -> bool:
    """True یعنی هنوز توی زمان انتظاره."""
    now = time.time()
    if now - cooldown.get(key, 0) < secs:
        return True
    cooldown[key] = now
    return False


def onoff(arg):
    a = (arg or "").strip().lower()
    if a in ("on", "روشن", "1"):
        return True
    if a in ("off", "خاموش", "0"):
        return False
    return None


def cc(chat_id) -> dict:
    return CFG["chats"].setdefault(str(chat_id), {})


def is_persian(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum("\u0600" <= c <= "\u06ff" for c in letters) / len(letters) > 0.5


async def safe_edit(event, text, **kw):
    try:
        await event.edit(text, **kw)
    except Exception:  # noqa
        pass


async def target_user(event, arg=""):
    """کاربر هدف: ریپلای، آرگومان (یوزرنیم/آیدی) یا طرف پی‌وی."""
    if event.is_reply:
        r = await event.get_reply_message()
        if r and r.sender_id:
            return r.sender_id
    if arg:
        return int(arg) if arg.lstrip("-").isdigit() else arg
    if event.is_private:
        return event.chat_id
    return None


async def http_json(url, params=None, headers=None, body=None, timeout=20):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout), headers=headers) as s:
        if body is not None:
            async with s.post(url, json=body) as r:
                r.raise_for_status()
                return await r.json(content_type=None)
        async with s.get(url, params=params) as r:
            r.raise_for_status()
            return await r.json(content_type=None)


async def http_text(url, timeout=20, limit=1_000_000):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as s:
        async with s.get(url) as r:
            r.raise_for_status()
            return (await r.content.read(limit)).decode("utf-8", "ignore")


# ───────────── پروفایل: ساعت + تاریخ ─────────────
async def sync_profile(clean: bool = False):
    """پروفایل رو با تنظیمات فعلی هماهنگ می‌کنه (clean=True یعنی همه‌چیز پاک بشه)."""
    try:
        me = await C().get_me()
        full = await C()(GetFullUserRequest(me))
        cur_last = me.last_name or ""
        cur_bio = full.full_user.about or ""
        base_last, base_bio = strip_clock(cur_last), strip_bio(cur_bio)

        ctext = clock_text() if (F["clock"] and not clean) else ""
        dtext = f"📅 {jalali_short()}" if (F["date"] and not clean) else ""

        last, bio_parts = base_last, [base_bio, dtext]
        if CFG["target"] == "bio":
            bio_parts.append(ctext)
        elif ctext:
            last = f"{base_last} {ctext}".strip()
        bio = " ".join(p for p in bio_parts if p)[:70]
        last = last[:64]

        kw = {}
        if last != cur_last:
            kw["last_name"] = last
        if bio != cur_bio:
            kw["about"] = bio
        if kw:
            await C()(UpdateProfileRequest(**kw))
    except FloodWaitError as e:
        log.warning("FloodWait %ss", e.seconds)
        await asyncio.sleep(e.seconds + 1)


async def refresh():
    state["last_key"] = None
    await sync_profile()
    state["last_key"] = profile_key()


core.hooks["refresh"] = refresh


async def clock_loop():
    while True:
        try:
            if state["authorized"] and (F["clock"] or F["date"]):
                k = profile_key()
                if k != state["last_key"]:
                    await sync_profile()
                    state["last_key"] = k
        except Exception as e:  # noqa
            log.exception("clock error: %s", e)
        now = datetime.now(TZ)
        nxt = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
        await asyncio.sleep(max((nxt - now).total_seconds(), 1))


async def online_loop():
    while True:
        try:
            if F["online"] and state["authorized"]:
                await C()(UpdateStatusRequest(offline=False))
        except Exception:  # noqa
            pass
        await asyncio.sleep(25)


async def set_me():
    me = await C().get_me()
    state["me"] = me.id


async def set_feature(key, value):
    F[key] = value
    save_settings()
    if key in ("clock", "date"):
        await refresh()


# ───────────── ماشین‌حساب امن ─────────────
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


# ───────────── دستورها ─────────────
ALIASES = {}


def alias(cmd, *names):
    for n in names:
        ALIASES[n] = cmd


alias("panel", "panel", "پنل")
alias("help", "help", "راهنما")
alias("ping", "ping", "پینگ")
alias("time", "time")
alias("date", "date", "تاریخ")
alias("id", "id", "آیدی")
alias("clock", "clock", "ساعت")
alias("afk", "afk", "آفلاین")
alias("del", "del", "حذف")
alias("type", "type", "تایپ")
alias("calc", "calc", "حساب")
alias("format", "format", "فرمت")
alias("reply", "reply", "جواب")
alias("canned", "snip", "متن")
alias("guard", "guard", "نگهبان")
alias("lock", "lock", "قفل")
alias("unlock", "unlock", "بازکردن")
alias("filter", "filter", "فیلتر")
alias("join", "join", "عضویت")
alias("friend", "friend", "دوست")
alias("ignore", "ignore", "نادیده")
alias("secretary", "secretary", "منشی")
alias("react", "react", "ریکت")
alias("mute", "mute", "سکوت")
alias("unmute", "unmute", "لغوسکوت")
alias("block", "block", "بلاک")
alias("unblock", "unblock", "آنبلاک")
alias("info", "info", "اطلاعات")
alias("save", "save", "ذخیره")
alias("download", "download", "دانلود")
alias("ai", "ai", "هوش")
alias("translate", "tr", "ترجمه")
alias("anim", "anim", "انیمیشن")
alias("cheat", "cheat", "تقلب")
alias("tts", "tts", "صدا")
alias("video", "video", "ویدیو")
alias("news", "news", "اخبار")
alias("music", "music", "آهنگ")
alias("currency", "fx", "ارز")
alias("logo", "logo", "لوگو")
alias("action", "action", "اکشن")
alias("online", "online", "آنلاین")
alias("seen", "seen", "سین")
alias("comment", "comment", "کامنت")
alias("mentionlog", "mention", "منشن")
alias("antidel", "antidel", "ضدحذف")
alias("about", "about", "درباره")
alias("status", "status", "وضعیت")
alias("auto", "auto", "خودکار")
alias("catch", "catch", "نجات", "autocatch")
alias("meowie", "meowie", "میویی")
alias("backup", "backup", "پشتیبان")
alias("restore", "restore", "بازیابی")
alias("automeow", "automeow", "میوخودکار")
alias("autofish", "autofish", "ماهیگیری", "ماهیگیر")
alias("autofridge", "autofridge", "یخچال", "یخچالی")
alias("autobat", "autobat", "خفاش")
alias("autocat", "autocat", "پیشی")
alias("show", "show", "نمایش")
alias("sched", "sched", "زمانبندی")
alias("alias", "alias", "الیاس", "میانبر")
alias("proxy", "proxy", "پروکسی")
alias("mstatus", "meowstatus", "meowhelp", "بازی")
alias("report", "report", "گزارش")
alias("quiet", "quiet", "خاموشی")
alias("update", "update", "آپدیت", "بروزرسانی")
meow.RESERVED.update(ALIASES)  # اسم الیاس‌های کاربر نباید با دستورهای سلف یکی باشه

SLASH_OK = {"automeow", "autofish", "autofridge", "autobat", "autocatch", "autocat"}  # این‌ها با «/» هم کار می‌کنن
CMD_PATTERN = (
    r"(?is)^([./])(" + "|".join(re.escape(a) for a in sorted(ALIASES, key=len, reverse=True))
    + r")(?:\s+(.*))?$"
)


def help_text() -> str:
    lines = ["📖 راهنما  (پنل دکمه‌ای: .پنل)", ""]
    for f in FEATS:
        lines.append(f"{f['emoji']} {f['name']}: {f['examples'][0]}")
    return "\n".join(lines)


SCHED_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*[-–—]\s*(\d{1,2}):(\d{2})$")


def parse_sched(text: str):
    """'23:00-07:00' → (دقیقه‌ی شروع، دقیقه‌ی پایان) یا None."""
    m = SCHED_RE.match((text or "").translate(FA2EN).strip())
    if not m:
        return None
    h1, m1, h2, m2 = map(int, m.groups())
    if not (0 <= h1 < 24 and 0 <= h2 < 24 and m1 < 60 and m2 < 60):
        return None
    return h1 * 60 + m1, h2 * 60 + m2


def quiet_now(now=None) -> bool:
    sch = parse_sched(CFG.get("afk_sched", ""))
    if not sch or sch[0] == sch[1]:
        return False
    now = now or datetime.now(TZ)
    cur = now.hour * 60 + now.minute
    a, b = sch
    return (a <= cur < b) if a < b else (cur >= a or cur < b)


def fmt_duration(sec: float) -> str:
    sec = int(sec)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    parts = []
    if d:
        parts.append(f"{d} روز")
    if h:
        parts.append(f"{h} ساعت")
    parts.append(f"{m} دقیقه")
    return " و ".join(parts)


def memory_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:  # noqa
        return None


def storage_ok() -> bool:
    d = os.path.dirname(core.SETTINGS_FILE) or "."
    return os.path.isdir(d) and os.access(d, os.W_OK)


async def c_status(event, arg):
    head, _, rest = arg.partition(" ")
    if head in ("چت", "chat", "game", "بازی"):
        return await event.edit(meow.status_text(event.chat_id))
    if head in ("اعلان", "notify"):
        v = onoff(rest)
        CFG["notify_restart"] = (not CFG["notify_restart"]) if v is None else v
        save_settings()
        return await event.edit("🔔 اعلان ریستارت " + ("روشن شد" if CFG["notify_restart"] else "خاموش شد"))
    t0 = time.perf_counter()
    try:
        await C().get_me()
        ping = f"{int((time.perf_counter() - t0) * 1000)}ms"
        tg = f"وصل ✅ ({ping})"
    except Exception:  # noqa
        tg = "مشکل در اتصال ❌"
    started = datetime.fromtimestamp(core.START_TIME, TZ)
    mem = memory_mb()
    on = [FEAT[k]["name"] for k, v in F.items() if v]
    bot = (f"@{botpanel.BOT['username']} ✅" if botpanel.BOT["running"]
           else ("توکن هست ولی وصل نیست ⚠️" if CFG["bot_token"] else "تنظیم نشده"))
    lines = [
        "🩺 وضعیت سلف",
        "",
        f"⏱ روشن بودن: {fmt_duration(time.time() - core.START_TIME)}",
        f"🚀 شروع: {jalali_long()} {started:%H:%M}" if started.date() == datetime.now(TZ).date()
        else f"🚀 شروع: {started:%Y-%m-%d %H:%M}",
        f"🔄 تعداد ریستارت‌ها: {CFG['restarts']}",
        f"🧠 حافظه: {mem:.0f} MB" if mem else "🧠 حافظه: نامشخص",
        f"📡 تلگرام: {tg}",
        f"🤖 بات پنل: {bot}",
        f"💾 ذخیره‌سازی: {'Volume ✅' if storage_ok() else 'بدون Volume ⚠️ (بعد از ریدیپلوی تنظیمات می‌پره)'}",
        f"🎛 قابلیت روشن: {len(on)} از {len(F)}" + (f"\n   {' ، '.join(on)}" if on else ""),
        f"🔔 اعلان ریستارت: {'روشن' if CFG['notify_restart'] else 'خاموش'}",
    ]
    await event.edit("\n".join(lines))


async def notify_start():
    """بعد از هر ریستارت (وقتی وارد شده باشی) توی Saved Messages خبر می‌ده."""
    CFG["restarts"] += 1
    save_settings()
    await updater.announce()
    if not CFG["notify_restart"]:
        return
    try:
        mem = memory_mb()
        await C().send_message(
            "me",
            f"🔄 سلف روشن شد — {jalali_long()} {datetime.now(TZ):%H:%M}"
            + (f"\n🧠 {mem:.0f} MB" if mem else "")
            + ("" if storage_ok() else "\n⚠️ Volume نیست؛ تنظیمات بعد از ریدیپلوی می‌پره")
            + "\n(خاموش کردن: .وضعیت اعلان off)")
    except Exception as e:  # noqa
        log.warning("restart notice failed: %r", e)


def toggle_keys():
    return [f["key"] for f in FEATS if f["toggle"]]


def panel_text() -> str:
    on = sum(1 for v in F.values() if v)
    lines = [f"🔥 پنل مدیریت سلف (🎛 {on} روشن)", ""]
    for i, k in enumerate(toggle_keys(), 1):
        lines.append(f"{i}. {'🟢' if F[k] else '🔴'} {FEAT[k]['emoji']} {FEAT[k]['name']}")
    lines += ["", "⌨️ روشن/خاموش: .پنل شماره   (مثلاً .پنل 2)", "همه خاموش: .پنل off",
              "📱 مینی‌اپ (هر چتی): .پنل مینی‌اپ",
              "📖 راهنما: .راهنما · 🎛 پنل دکمه‌ای: .پنل"]
    return "\n".join(lines)


async def self_mini_header() -> str:
    """هدر مدیریتی خفن: اسم اکانت + تایم سلف + شمارش — برای پیام مینی‌اپ."""
    try:
        me = await C().get_me()
    except Exception:  # noqa
        me = None
    on = sum(1 for v in F.values() if v)
    s = int(time.time() - core.START_TIME)
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    up = " و ".join(x for x in ((f"{d} روز" if d else ""), (f"{h} ساعت" if h else ""), f"{m} دقیقه") if x)
    try:
        loops = len(meow.TASKS)
    except Exception:  # noqa
        loops = 0
    if me is not None:
        nm, un, uid = dname(me), getattr(me, "username", None), getattr(me, "id", None)
        acc = f"👤 <b>{nm}</b>" + (f" (@{un} · <code>{uid}</code>)" if un else (f" (<code>{uid}</code>)" if uid else ""))
    else:
        acc = "👤 —"
    return (f"🔥 <b>مدیریت سلف</b>\n{acc}\n⏱ آپتایم سلف: {up} · 🎛 <b>{on}</b> روشن"
            + (f" · 🔄 {loops} حلقه‌ی بازی" if loops else ""))


async def c_panel_app(event):
    """پست لینک مینی‌اپ توی همین چت — هرجا .پنل مینی‌اپ بزنی میاد."""
    url, web = miniapp.app_url(), miniapp.web_url()
    header = await self_mini_header()
    if not url:
        return await safe_edit(event, header + "\n\n⚠️ دامنه ست نیست؛ توی Railway متغیر <b>HUB_DOMAIN</b> رو بذار تا دکمه‌ی مینی‌اپ بیاد.")
    btns = [[Button.url("📱 باز کردن مینی‌اپ", url)]]
    if web:
        btns.append([Button.url("🌐 پنل وب", web)])
    try:
        msg = await C().send_message(event.chat_id, header + "\n\n👇 مینی‌اپ مدیریتی (اسم اکانت، تایم سلف و همه‌چی توشه):",
                                     parse_mode="html", buttons=btns, link_preview=False)
    except Exception:  # noqa
        return await safe_edit(event, header + f"\n\n📱 مینی‌اپ:\n{url}")
    try:
        await event.delete()
    except Exception:  # noqa
        pass
    if CFG["panel_ttl"] > 0 and msg:
        asyncio.create_task(_delete_later(msg, CFG["panel_ttl"]))


THEMES = {"classic": "classic", "کلاسیک": "classic", "mono": "mono", "تکرنگ": "mono",
          "تک‌رنگ": "mono", "plain": "plain", "ساده": "plain"}


def options_text() -> str:
    ttl = CFG["panel_ttl"]
    n = len(CFG["panel_chats"])
    return (
        "🎛 گزینه‌های پنل\n\n"
        f"⏱ حذف خودکار: {f'{ttl} ثانیه' if ttl else 'خاموش'}   (.پنل زمان 120)\n"
        f"🔒 فقط چت‌های مجاز: {'روشن' if CFG['panel_restrict'] else 'خاموش'}   (.پنل محدود on)\n"
        f"✅ چت‌های مجاز: Saved Messages + {n} چت   (.پنل اینجا)\n"
        f"🎨 رنگ دکمه‌ها: {CFG['theme']}   (.پنل رنگ classic | mono | plain)\n"
        f"🌙 ساعت سکوت: {CFG['afk_sched'] or 'خاموش'}   (.آفلاین ساعت 23:00-07:00)"
    )


async def c_panel(event, arg):
    a = arg.translate(FA2EN).lower().strip()
    keys = toggle_keys()
    head, _, rest = a.partition(" ")
    rest = rest.strip()

    # گزینه‌های خود پنل
    if head in ("تنظیمات", "options", "opts"):
        return await safe_edit(event, options_text())
    if head in ("زمان", "ttl"):
        if not rest.isdigit():
            return await safe_edit(event, "مثال: .پنل زمان 120   (0 = پاک نشه)")
        CFG["panel_ttl"] = min(int(rest), 3600)
        save_settings()
        t = CFG["panel_ttl"]
        return await safe_edit(event, f"⏱ پنل بعد از {t} ثانیه پاک می‌شه" if t else "⏱ حذف خودکار پنل خاموش شد")
    if head in ("اینجا", "here"):
        lst, cid = CFG["panel_chats"], event.chat_id
        if cid in lst:
            lst.remove(cid)
            msg = "❌ این چت از چت‌های مجاز پنل حذف شد"
        else:
            lst.append(cid)
            msg = "✅ این چت برای نمایش پنل مجاز شد"
        save_settings()
        if not CFG["panel_restrict"]:
            msg += "\n(محدودیت خاموشه؛ با «.پنل محدود on» روشنش کن)"
        return await safe_edit(event, msg)
    if head in ("محدود", "restrict"):
        v = onoff(rest)
        CFG["panel_restrict"] = (not CFG["panel_restrict"]) if v is None else v
        save_settings()
        return await safe_edit(event, "🔒 پنل فقط توی Saved Messages و چت‌های مجاز نمایش داده می‌شه"
                               if CFG["panel_restrict"] else "🔓 پنل توی همه‌ی چت‌ها مجازه")
    if head in ("رنگ", "theme"):
        th = THEMES.get(rest)
        if not th:
            return await safe_edit(event, "رنگ‌بندی: classic (سبز/قرمز/آبی) | mono (همه آبی) | plain (بدون رنگ)")
        CFG["theme"] = th
        save_settings()
        return await safe_edit(event, f"🎨 رنگ‌بندی دکمه‌ها: {th}\nبا .پنل ببین")
    if head in ("app", "miniapp", "مینی‌اپ", "مینیاپ", "مینی"):
        return await c_panel_app(event)

    if a in ("off", "خاموش"):
        for k in F:
            F[k] = False
        save_settings()
        await refresh()
        return await safe_edit(event, panel_text())
    if a.split()[:1] and a.split()[0].isdigit():
        parts = a.split()
        i = int(parts[0])
        if 1 <= i <= len(keys):
            v = onoff(parts[1]) if len(parts) > 1 else None
            await set_feature(keys[i - 1], (not F[keys[i - 1]]) if v is None else v)
        return await safe_edit(event, panel_text())
    if a in ("متن", "text"):
        return await safe_edit(event, panel_text())

    uname = botpanel.BOT.get("username")
    allowed = (not CFG["panel_restrict"]) or event.chat_id == state.get("me") or event.chat_id in CFG["panel_chats"]
    if uname and allowed:  # حالت اصلی: پنل مستقیم توی همین چت (inline)
        try:
            results = await C().inline_query(uname, "panel")
            if results:
                sent = await results[0].click(event.chat_id)
                await event.delete()
                if CFG["panel_ttl"] > 0 and sent:
                    asyncio.create_task(_delete_later(sent, CFG["panel_ttl"]))
                return
        except Exception as e:  # noqa
            log.warning("inline panel failed: %r", e)
    res = await botpanel.send_panel()  # جایگزین: ارسال توی چت خصوصی با بات
    if res == "ok" and not allowed:
        await safe_edit(event, f"🔒 این چت برای پنل مجاز نیست؛ پنل رو توی @{uname} فرستادم.\n(.پنل اینجا برای مجاز کردن)")
    elif res == "ok":
        await safe_edit(
            event,
            f"🎛 پنل رو توی @{uname} فرستادم.\n"
            "برای اینکه مستقیم توی همین چت بیاد: @BotFather ← /setinline ← بات رو انتخاب کن ← یه متن بنویس.")
    elif res == "not_started":
        await safe_edit(event, f"اول توی @{uname} بزن Start، بعد دوباره .پنل رو بزن.")
    elif res in ("no_token", "no_me"):
        if miniapp.app_url():  # بات نیست ولی دامنه هست → هدر خفن + دکمه‌ی مینی‌اپ
            try:
                return await event.edit(await self_mini_header(), parse_mode="html",
                                        buttons=[[Button.url("📱 باز کردن مینی‌اپ", miniapp.app_url())]],
                                        link_preview=False)
            except Exception:  # noqa
                pass
        await safe_edit(
            event,
            "بات پنل تنظیم نشده (توکن BotFather رو توی پنل وب بذار). فعلاً پنل متنی:\n\n" + panel_text())
    else:
        await safe_edit(event, f"خطا توی بات پنل: {res}\n\n" + panel_text())


async def _delete_later(msg, secs):
    await asyncio.sleep(secs)
    try:
        await msg.delete()
    except Exception:  # noqa
        pass


async def c_help(event, arg):
    await event.edit(help_text())


async def c_about(event, arg):
    await event.edit("📖 " + FEAT["about"]["desc"] + f"\n\n{len(FEATS)} قابلیت | .پنل | .راهنما")


async def c_ping(event, arg):
    t0 = time.perf_counter()
    await event.edit("...")
    await event.edit(f"pong 🏓 {int((time.perf_counter() - t0) * 1000)}ms")


async def c_time(event, arg):
    await event.edit(f"🕒 {datetime.now(TZ):%Y-%m-%d  %H:%M:%S}")


async def c_date(event, arg):
    v = onoff(arg)
    if v is not None:  # .تاریخ on / off ← تاریخ شمسی توی بیو
        await set_feature("date", v)
        return await event.edit("📅 تاریخ توی بیو " + ("روشن شد ✅" if v else "خاموش شد ❌"))
    await event.edit(f"📅 {jalali_long()}\n🗓 {datetime.now(TZ):%Y-%m-%d}")


async def c_id(event, arg):
    if event.is_reply:
        r = await event.get_reply_message()
        await event.edit(f"user: `{r.sender_id}`\nchat: `{event.chat_id}`")
    else:
        await event.edit(f"chat: `{event.chat_id}`")


async def c_clock(event, arg):
    if arg == "on":
        F["clock"] = True
        msg = "ساعت روشن شد ✅"
    elif arg == "off":
        F["clock"] = False
        msg = "ساعت خاموش شد ❌"
    elif arg in ("name", "bio"):
        CFG["target"] = "bio" if arg == "bio" else "last_name"
        msg = "محل ساعت عوض شد ✅"
    elif arg.startswith("font") and arg.split()[-1] in core.FONTS:
        CFG["font"] = arg.split()[-1]
        msg = "فونت عوض شد ✅"
    elif arg.startswith("emoji"):
        e = arg[5:].strip()
        CFG["emoji"] = "" if e in ("", "off", "none") else e[:2]
        msg = "ایموجی عوض شد ✅"
    else:
        return await event.edit(help_text())
    save_settings()
    await refresh()
    await event.edit(msg)


async def c_afk(event, arg):
    head, _, rest = arg.partition(" ")
    if head in ("ساعت", "time", "schedule"):  # ساعت سکوت (آفلاین خودکار)
        rest = rest.strip()
        if rest.lower() in ("off", "خاموش", ""):
            CFG["afk_sched"] = ""
            save_settings()
            return await event.edit("⏰ ساعت سکوت خاموش شد")
        if not parse_sched(rest):
            return await event.edit("مثال: .آفلاین ساعت 23:00-07:00")
        CFG["afk_sched"] = rest.translate(FA2EN)
        save_settings()
        return await event.edit(f"⏰ بین {CFG['afk_sched']} خودکار آفلاین می‌شم 🌙")
    if arg.lower() in ("off", "خاموش"):
        F["afk"] = False
        msg = "برگشتم ✅"
    else:
        if arg:
            CFG["afk_text"] = arg
        F["afk"] = True
        msg = "حالت آفلاین روشن شد 🌙"
    cooldown.clear()
    save_settings()
    await event.edit(msg)


async def c_del(event, arg):
    a = arg.translate(FA2EN)
    n = min(int(a) if a.isdigit() else 1, 100)
    msgs = [m async for m in C().iter_messages(event.chat_id, from_user="me", limit=n + 1)]
    await C().delete_messages(event.chat_id, msgs)


async def c_type(event, arg):
    if not arg:
        return
    out = ""
    for w in arg.split(" ")[:40]:
        out = f"{out} {w}".strip()
        await safe_edit(event, out + " ▌")
        await asyncio.sleep(0.4)
    await safe_edit(event, out)


async def c_calc(event, arg):
    try:
        await event.edit(f"{arg} = {safe_calc(arg.translate(FA2EN))}")
    except ZeroDivisionError:
        await event.edit("تقسیم بر صفر 😅")
    except Exception:  # noqa
        await event.edit("عبارت نامعتبره")


# ───── فرمت / جواب‌ها / متن‌های آماده ─────
FMT = {
    "bold": types.MessageEntityBold,
    "italic": types.MessageEntityItalic,
    "mono": types.MessageEntityCode,
    "spoiler": types.MessageEntitySpoiler,
    "strike": types.MessageEntityStrike,
    "underline": types.MessageEntityUnderline,
}
FMT_ALIAS = {"بولد": "bold", "ایتالیک": "italic", "مونو": "mono",
             "اسپویلر": "spoiler", "خط‌خورده": "strike", "زیرخط": "underline"}


async def c_format(event, arg):
    low = arg.lower().strip()
    if low in ("off", "خاموش"):
        F["format"] = False
        msg = "فرمت خودکار خاموش شد ❌"
    else:
        mode = FMT_ALIAS.get(low, low)
        if mode not in FMT:
            return await event.edit("حالت‌ها: " + " | ".join(FMT) + " | off")
        CFG["fmt"], F["format"] = mode, True
        msg = f"فرمت خودکار روشن شد ✅ ({mode})"
    save_settings()
    await event.edit(msg)


async def c_reply(event, arg):
    low = arg.lower()
    if low in ("", "لیست", "list"):
        text = "\n".join(f"• {k} ← {v}" for k, v in CFG["replies"].items()) or "هنوز چیزی ثبت نشده"
        return await event.edit(f"💬 جواب‌های کلمه‌ای:\n{text}")
    if low.startswith(("حذف", "del")):
        kw = arg.split(None, 1)[-1].strip().lower() if " " in arg else ""
        ok = CFG["replies"].pop(kw, None) is not None
        save_settings()
        return await event.edit("حذف شد ✅" if ok else "همچین کلمه‌ای نبود")
    if "|" in arg:
        kw, resp = (x.strip() for x in arg.split("|", 1))
        if kw and resp:
            CFG["replies"][kw.lower()] = resp
            F["autoreply"] = True
            save_settings()
            return await event.edit(f"ثبت شد ✅\nهر کی «{kw}» بفرسته، جواب می‌دم.")
    await event.edit("مثال: .جواب سلام | سلام خوبی؟")


async def c_canned(event, arg):
    if arg.startswith(("ذخیره", "save")):
        body = arg.split(None, 1)[1] if " " in arg else ""
        if "|" in body:
            name, text = (x.strip() for x in body.split("|", 1))
            if name and text:
                CFG["canned"][name] = text
                save_settings()
                return await event.edit(f"ذخیره شد ✅ با «.متن {name}» می‌فرستیش")
        return await event.edit("مثال: .متن ذخیره سلام | سلام، خوبی؟")
    if arg in ("", "لیست", "list"):
        names = "\n".join(f"• {k}" for k in CFG["canned"]) or "هنوز چیزی ذخیره نشده"
        return await event.edit(f"📋 متن‌های آماده:\n{names}")
    if arg.startswith(("حذف", "del")):
        name = arg.split(None, 1)[1].strip() if " " in arg else ""
        ok = CFG["canned"].pop(name, None) is not None
        save_settings()
        return await event.edit("حذف شد ✅" if ok else "پیدا نشد")
    text = CFG["canned"].get(arg)
    if text:
        await event.edit(text, parse_mode=None)
    else:
        await event.edit("همچین متنی ذخیره نشده؛ .متن لیست")


def make_toggle(key, on_msg, off_msg):
    async def fn(event, arg):
        v = onoff(arg)
        v = (not F[key]) if v is None else v
        await set_feature(key, v)
        await event.edit(on_msg if v else off_msg)
    return fn


c_seen = make_toggle("autoseen", "سین خودکار روشن شد 👀", "سین خودکار خاموش شد")
c_online = make_toggle("online", "همیشه آنلاین روشن شد 🟢", "همیشه آنلاین خاموش شد")
c_mentionlog = make_toggle("mention", "ذخیره منشن‌ها روشن شد 🔔", "ذخیره منشن‌ها خاموش شد")
c_antidel = make_toggle("antidel", "ضد حذف روشن شد 🗑", "ضد حذف خاموش شد")


async def c_secretary(event, arg):
    v = onoff(arg)
    if v is None and arg:
        CFG["secretary_text"], v = arg, True
    elif v is None:
        v = not F["secretary"]
    F["secretary"] = v
    save_settings()
    await event.edit("منشی روشن شد 🧑‍💼" if v else "منشی خاموش شد")


# ───── مدیریت گروه ─────
LINK_RE = re.compile(r"(?i)(https?://|www\.|t\.me/|telegram\.me/|@[a-z]\w{3,})")
LOCKS = {"لینک": "link", "فوروارد": "forward", "عکس": "photo", "ویدیو": "video",
         "استیکر": "sticker", "ویس": "voice", "گیف": "gif", "فایل": "file", "منشن": "mention"}


def lock_violation(m, locks):
    t = m.raw_text or ""
    ents = m.entities or []
    checks = {
        "link": bool(LINK_RE.search(t)) or any(
            isinstance(e, (types.MessageEntityUrl, types.MessageEntityTextUrl)) for e in ents),
        "forward": bool(m.fwd_from),
        "photo": bool(m.photo),
        "video": bool(m.video),
        "sticker": bool(m.sticker),
        "voice": bool(m.voice),
        "gif": bool(m.gif),
        "file": bool(m.document) and not (m.sticker or m.voice or m.video or m.gif),
        "mention": bool(re.search(r"@\w{4,}", t)),
    }
    for k in locks:
        if checks.get(k):
            return k
    return None


async def need_group(event):
    if event.is_private:
        await event.edit("این دستور فقط توی گروه کار می‌کنه")
        return False
    return True


async def c_guard(event, arg):
    if not await need_group(event):
        return
    v = onoff(arg)
    c = cc(event.chat_id)
    v = (not c.get("guard")) if v is None else v
    c["guard"] = v
    if v:
        F["guard"] = True
    save_settings()
    await event.edit("🛡 نگهبان چت روشن شد (باید ادمین با دسترسی حذف پیام باشم)" if v
                     else "🛡 نگهبان چت خاموش شد")


async def c_lock(event, arg):
    if not await need_group(event):
        return
    c = cc(event.chat_id)
    locks = c.setdefault("locks", [])
    if arg in ("", "لیست", "list"):
        return await event.edit("🔒 قفل‌های فعال: " + (" ، ".join(locks) or "هیچی"))
    key = LOCKS.get(arg, arg)
    if key not in LOCKS.values():
        return await event.edit("انواع: " + " | ".join(LOCKS))
    if key not in locks:
        locks.append(key)
    F["locks"] = True
    save_settings()
    await event.edit(f"🔒 «{arg}» قفل شد")


async def c_unlock(event, arg):
    if not await need_group(event):
        return
    c = cc(event.chat_id)
    locks = c.setdefault("locks", [])
    if arg in ("همه", "all"):
        locks.clear()
    else:
        key = LOCKS.get(arg, arg)
        if key in locks:
            locks.remove(key)
    save_settings()
    await event.edit("🔓 باز شد. قفل‌های فعال: " + (" ، ".join(locks) or "هیچی"))


async def c_filter(event, arg):
    if not await need_group(event):
        return
    c = cc(event.chat_id)
    words = c.setdefault("words", [])
    low = arg.lower()
    if low in ("", "لیست", "list"):
        return await event.edit("🚫 کلمات ممنوعه: " + (" ، ".join(words) or "هیچی"))
    head, _, rest = arg.partition(" ")
    rest = rest.strip().lower()
    if head in ("اضافه", "add") and rest:
        if rest not in words:
            words.append(rest)
        F["filter"] = True
        msg = f"🚫 «{rest}» به فیلتر اضافه شد"
    elif head in ("حذف", "del") and rest:
        if rest in words:
            words.remove(rest)
        msg = f"«{rest}» از فیلتر حذف شد"
    elif low in ("off", "خاموش"):
        words.clear()
        msg = "فیلتر این گروه پاک شد"
    else:
        msg = "مثال: .فیلتر اضافه کلمه"
    save_settings()
    await event.edit(msg)


async def c_join(event, arg):
    if not await need_group(event):
        return
    c = cc(event.chat_id)
    if arg.lower() in ("off", "خاموش", ""):
        c.pop("join", None)
        save_settings()
        return await event.edit("🔐 عضویت اجباری خاموش شد")
    ent = await C().get_entity(arg)
    c["join"] = arg
    F["forcejoin"] = True
    save_settings()
    await event.edit(f"🔐 فقط اعضای «{dname(ent)}» می‌تونن اینجا حرف بزنن (باید ادمین باشم)")


async def c_react(event, arg):
    c = cc(event.chat_id)
    if arg.lower() in ("off", "خاموش", ""):
        c.pop("react", None)
        save_settings()
        return await event.edit("ریکت خودکار این چت خاموش شد")
    c["react"] = arg.strip()[:4]
    F["react"] = True
    save_settings()
    await event.edit(f"ریکت خودکار این چت: {c['react']}")


async def c_mute(event, arg):
    if not await need_group(event):
        return
    uid = await target_user(event, arg)
    if not isinstance(uid, int):
        return await event.edit("روی پیام اون شخص ریپلای کن")
    c = cc(event.chat_id)
    muted = c.setdefault("muted", [])
    if uid not in muted:
        muted.append(uid)
    F["mute"] = True
    save_settings()
    try:
        await C().edit_permissions(event.chat_id, uid, send_messages=False)
        extra = "(محدود شد)"
    except Exception:  # noqa
        extra = "(ادمین نیستم؛ فقط پیام‌هاش رو پاک می‌کنم اگه دسترسی حذف داشته باشم)"
    await event.edit(f"🔇 ساکت شد {extra}")


async def c_unmute(event, arg):
    if not await need_group(event):
        return
    uid = await target_user(event, arg)
    c = cc(event.chat_id)
    if isinstance(uid, int) and uid in c.get("muted", []):
        c["muted"].remove(uid)
        save_settings()
    try:
        await C().edit_permissions(event.chat_id, uid)
    except Exception:  # noqa
        pass
    await event.edit("🔊 سکوت برداشته شد")


async def c_friend(event, arg):
    await _people(event, arg, "friends", "🤝 دوست‌ها", "اضافه شد به دوست‌ها 🤝", "friends")


async def c_ignore(event, arg):
    await _people(event, arg, "ignored", "🙈 نادیده‌ها", "نادیده گرفته می‌شه 🙈", None)


async def _people(event, arg, key, title, add_msg, feature):
    if arg in ("لیست", "list"):
        lines = []
        for uid in CFG[key]:
            try:
                lines.append(f"• {dname(await C().get_entity(uid))} (`{uid}`)")
            except Exception:  # noqa
                lines.append(f"• `{uid}`")
        return await event.edit(f"{title}:\n" + ("\n".join(lines) or "خالیه"))
    uid = await target_user(event)
    if not isinstance(uid, int):
        return await event.edit("روی پیام اون شخص ریپلای کن (یا توی پی‌وی‌ش بنویس)")
    if arg in ("حذف", "del"):
        if uid in CFG[key]:
            CFG[key].remove(uid)
        save_settings()
        return await event.edit("حذف شد ✅")
    if uid not in CFG[key]:
        CFG[key].append(uid)
    if feature:
        F[feature] = True
    save_settings()
    await event.edit(add_msg)


# ───── کاربر ─────
async def c_block(event, arg):
    uid = await target_user(event, arg)
    if uid is None:
        return await event.edit("روی پیام اون شخص ریپلای کن یا توی پی‌وی‌ش بنویس")
    await C()(BlockRequest(await C().get_input_entity(uid)))
    await event.edit("⛔ بلاک شد")


async def c_unblock(event, arg):
    uid = await target_user(event, arg)
    if uid is None:
        return await event.edit("روی پیام اون شخص ریپلای کن یا توی پی‌وی‌ش بنویس")
    await C()(UnblockRequest(await C().get_input_entity(uid)))
    await event.edit("✅ آنبلاک شد")


async def c_info(event, arg):
    text, _ = await meow.info_report(C(), event, arg)
    await event.edit(text, parse_mode="html", link_preview=False)


async def c_save(event, arg):
    if not event.is_reply:
        return await event.edit("روی یه پیام ریپلای کن")
    r = await event.get_reply_message()
    if r.media and getattr(r.media, "ttl_seconds", None):
        return await event.edit("پیام‌های تایمردار قابل ذخیره نیستن")
    try:
        await C().forward_messages("me", r)
        await event.edit("📷 توی Saved Messages ذخیره شد ✅")
    except Exception:  # noqa
        await event.edit("این چت اجازه‌ی ذخیره نمی‌ده")


# ───── دانلود ─────
async def public_host_ok(url: str) -> bool:
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            p.hostname, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


async def fetch_file(url: str, limit: int = 100 * 1024 * 1024) -> str:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as s:
        for _ in range(5):
            if not await public_host_ok(url):
                raise ValueError("آدرس مجاز نیست")
            async with s.get(url, allow_redirects=False) as r:
                loc = r.headers.get("Location")
                if r.status in (301, 302, 303, 307, 308) and loc:
                    url = urllib.parse.urljoin(url, loc)
                    continue
                r.raise_for_status()
                if (r.content_length or 0) > limit:
                    raise ValueError("فایل خیلی بزرگه (حداکثر ۱۰۰ مگ)")
                name = os.path.basename(urllib.parse.urlparse(url).path) or "file"
                path = os.path.join(tempfile.mkdtemp(), name[:80])
                size = 0
                with open(path, "wb") as f:
                    async for chunk in r.content.iter_chunked(1 << 16):
                        size += len(chunk)
                        if size > limit:
                            raise ValueError("فایل خیلی بزرگه (حداکثر ۱۰۰ مگ)")
                        f.write(chunk)
                return path
    raise ValueError("ریدایرکت بیش از حد")


async def c_download(event, arg):
    if not arg.startswith(("http://", "https://")):
        return await event.edit("مثال: .دانلود https://example.com/file.pdf")
    await event.edit("⬇️ در حال دانلود...")
    try:
        path = await fetch_file(arg.split()[0])
    except Exception as e:  # noqa
        return await event.edit(f"خطا: {e}")
    try:
        await event.edit("⬆️ در حال ارسال...")
        await C().send_file(event.chat_id, path)
        await event.delete()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ───── هوش مصنوعی / ترجمه / اطلاعات ─────
async def c_ai(event, arg):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return await event.edit("🤖 متغیر ANTHROPIC_API_KEY توی Railway تنظیم نشده")
    prompt = arg
    if event.is_reply:
        r = await event.get_reply_message()
        prompt = f"{r.raw_text}\n\n{arg}".strip() if r and r.raw_text else arg
    if not prompt:
        return await event.edit("مثال: .هوش فرق HTTP و HTTPS چیه؟")
    await event.edit("🤖 ...")
    data = await http_json(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        body={
            "model": os.getenv("AI_MODEL", "claude-haiku-4-5-20251001"),
            "max_tokens": 900,
            "system": "کوتاه و مفید جواب بده و به زبان خود کاربر پاسخ بده.",
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    text = "".join(b.get("text", "") for b in data.get("content", []))
    await event.edit(("🤖 " + text)[:4000], parse_mode=None)


LANGS = {"fa", "en", "ar", "tr", "de", "fr", "es", "ru", "it", "zh", "ja", "ko", "hi", "ur"}


async def c_translate(event, arg):
    lang, text = None, arg
    head, _, rest = arg.partition(" ")
    if head.lower() in LANGS and (rest.strip() or event.is_reply):
        lang, text = head.lower(), rest.strip()
    if not text and event.is_reply:
        r = await event.get_reply_message()
        text = r.raw_text or ""
    if not text:
        return await event.edit("مثال: .ترجمه hello  |  .ترجمه de سلام")
    lang = lang or ("en" if is_persian(text) else "fa")
    data = await http_json(
        "https://api.mymemory.translated.net/get",
        params={"q": text[:480], "langpair": f"autodetect|{lang}"},
    )
    out = (data.get("responseData") or {}).get("translatedText")
    if not out:
        return await event.edit("ترجمه نشد")
    await event.edit(f"🌐 ({lang})\n{out}", parse_mode=None)


async def c_news(event, arg):
    url = os.getenv("NEWS_RSS", "https://feeds.bbci.co.uk/persian/rss.xml")
    await event.edit("📰 ...")
    root = ET.fromstring(await http_text(url))
    items = root.findall(".//item")[:6]
    lines = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        if title:
            lines.append(f"• {title}\n{link}")
    await event.edit("📰 آخرین اخبار:\n\n" + ("\n\n".join(lines) or "خبری پیدا نشد"), link_preview=False)


async def c_music(event, arg):
    if not arg:
        return await event.edit("مثال: .آهنگ Shape of You")
    data = await http_json("https://itunes.apple.com/search",
                           params={"term": arg, "media": "music", "entity": "song", "limit": 5})
    res = data.get("results", [])
    if not res:
        return await event.edit("چیزی پیدا نشد 🎵")
    lines = []
    for r in res:
        lines.append(f"🎵 {r.get('trackName')} — {r.get('artistName')}\n{r.get('previewUrl') or r.get('trackViewUrl', '')}")
    await event.edit("\n\n".join(lines), link_preview=False)


async def c_video(event, arg):
    if not arg:
        return await event.edit("مثال: .ویدیو آموزش پایتون")
    q = urllib.parse.quote(arg)
    await event.edit(
        f"📹 جستجوی «{arg}»:\n\n▶️ YouTube:\nhttps://www.youtube.com/results?search_query={q}\n\n"
        f"🇮🇷 آپارات:\nhttps://www.aparat.com/search/{q}",
        link_preview=False,
    )


TGJU_PAGES = ["https://www.tgju.org/currency", "https://www.tgju.org/gold-chart", "https://www.tgju.org/coin"]
TGJU_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
}
ROW_TAG_RE = re.compile(r"<tr\b[^>]*data-market-nameslug=[^>]*>", re.I)
SLUG_RE = re.compile(r"""data-market-nameslug=["']([^"']+)["']""", re.I)
PRICE_RE = re.compile(r"""data-price=["']([^"']+)["']""", re.I)
# emoji, نام، slug توی tgju، اسم‌های مجاز برای فیلتر
RATE_ITEMS = [
    ("💵", "دلار", "price_dollar_rl", ("usd", "dollar", "دلار")),
    ("💶", "یورو", "price_eur", ("eur", "euro", "یورو")),
    ("💷", "پوند", "price_gbp", ("gbp", "پوند")),
    ("🇦🇪", "درهم امارات", "price_aed", ("aed", "درهم")),
    ("🇹🇷", "لیر ترکیه", "price_try", ("try", "lir", "لیر")),
    ("🥇", "طلای ۱۸ (هر گرم)", "geram18", ("gold", "طلا", "18")),
    ("🏅", "مثقال طلا", "mesghal", ("mesghal", "مثقال")),
    ("🪙", "سکه امامی", "sekee", ("coin", "سکه", "emami", "امامی")),
    ("🪙", "سکه بهار آزادی", "sekeb", ("azadi", "بهار", "آزادی")),
    ("🪙", "نیم سکه", "nim", ("nim", "نیم")),
    ("🪙", "ربع سکه", "rob", ("rob", "ربع")),
    ("🪙", "سکه گرمی", "gerami", ("gerami", "گرمی")),
]
_rates_cache = {"t": 0.0, "data": {}}


def parse_tgju(page_html: str) -> dict:
    """از جدول‌های tgju، slug → قیمت (ریال) رو درمیاره."""
    out = {}
    for tag in ROW_TAG_RE.findall(page_html):
        s_, p_ = SLUG_RE.search(tag), PRICE_RE.search(tag)
        if not (s_ and p_):
            continue
        num = re.sub(r"[^\d.]", "", p_.group(1).translate(FA2EN))
        try:
            out[s_.group(1)] = float(num)
        except ValueError:
            pass
    return out


async def get_tgju() -> dict:
    if time.time() - _rates_cache["t"] < 30 and _rates_cache["data"]:
        return _rates_cache["data"]

    async def one(url):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), headers=TGJU_HEADERS) as s:
                async with s.get(url) as r:
                    r.raise_for_status()
                    return parse_tgju((await r.content.read(3_000_000)).decode("utf-8", "ignore"))
        except Exception as e:  # noqa
            log.warning("tgju %s: %r", url, e)
            return {}

    merged = {}
    for part in await asyncio.gather(*(one(u) for u in TGJU_PAGES)):
        merged.update(part)
    if not merged:
        raise RuntimeError("tgju جواب نداد")
    _rates_cache.update(t=time.time(), data=merged)
    return merged


def toman(rial: float) -> str:
    return digits(f"{int(round(rial / 10)):,}")


async def c_currency(event, arg):
    await event.edit("💱 ...")
    a = arg.translate(FA2EN).strip().lower()
    amount = None
    m = re.match(r"^([\d.,]+)\s+(.+)$", a)
    if m:
        try:
            amount, a = float(m.group(1).replace(",", "")), m.group(2).strip()
        except ValueError:
            pass
    sel = RATE_ITEMS
    if a:
        sel = [i for i in RATE_ITEMS if a in i[3] or a == i[2]]
        if not sel:
            return await event.edit("نام ارز/سکه رو نشناختم. مثال: .ارز دلار | .ارز 100 یورو | .ارز سکه")
    try:
        rates = await get_tgju()
    except Exception:  # noqa
        return await event.edit(
            "⚠️ سایت tgju جواب نداد (ممکنه IP سرور رو بلاک کرده باشه یا ظاهر سایت عوض شده باشه).\n"
            "نرخ بازار آزاد رو از https://www.tgju.org ببین.", link_preview=False)
    lines = [f"💱 نرخ بازار آزاد — {digits(datetime.now(TZ).strftime('%H:%M'))}\n"]
    for emoji, name, slug, _ in sel:
        r = rates.get(slug)
        if r is None:
            continue
        if amount:
            lines.append(f"{emoji} {digits(f'{amount:g}')} {name} = {toman(amount * r)} تومان")
        else:
            lines.append(f"{emoji} {name}: {toman(r)} تومان")
    if len(lines) == 1:
        return await event.edit("برای این مورد قیمتی پیدا نشد")
    if not a:
        try:
            cg = await http_json("https://api.coingecko.com/api/v3/simple/price",
                                 params={"ids": "bitcoin,ethereum", "vs_currencies": "usd"})
            lines.append(f"\n₿ BTC: ${cg['bitcoin']['usd']:,}\nΞ ETH: ${cg['ethereum']['usd']:,}")
        except Exception:  # noqa
            pass
    lines.append("\nمنبع: tgju.org")
    await event.edit("\n".join(lines))


TTS_LANGS = {"en", "ar", "tr", "de", "fr", "es", "ru", "hi", "ur", "it", "pt", "ja", "ko"}


async def c_tts(event, arg):
    lang, text = "en", arg
    head, _, rest = arg.partition(" ")
    if head.lower() in TTS_LANGS and rest.strip():
        lang, text = head.lower(), rest.strip()
    if not text:
        return await event.edit("مثال: .صدا hello my friend")
    if is_persian(text):
        return await event.edit("Google TTS فارسی نداره. مثال: .صدا en hello")
    await event.edit("🔊 ...")
    from gtts import gTTS  # lazy
    path = os.path.join(tempfile.mkdtemp(), "voice.mp3")
    await asyncio.get_running_loop().run_in_executor(None, lambda: gTTS(text[:500], lang=lang).save(path))
    try:
        await C().send_file(event.chat_id, path, voice_note=True)
        await event.delete()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ───── سرگرمی ─────
ANIMS = {
    "ماه": ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘", "🌑"],
    "قلب": ["❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "❤️"],
    "لودینگ": ["▱▱▱▱▱", "▰▱▱▱▱", "▰▰▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰ ✅"],
    "ساعت": ["🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚", "🕛"],
    "موج": ["🌊", "🌊🌊", "🌊🌊🌊", "🌊🌊🌊🌊", "🌊🌊🌊🌊🌊"],
}
ANIM_EN = {"moon": "ماه", "heart": "قلب", "load": "لودینگ", "clock": "ساعت", "wave": "موج"}


async def c_anim(event, arg):
    name = ANIM_EN.get(arg.lower(), arg)
    frames = ANIMS.get(name)
    if not frames:
        return await event.edit("انیمیشن‌ها: " + " | ".join(ANIMS))
    for f in frames:
        await safe_edit(event, f)
        await asyncio.sleep(0.7)


async def c_cheat(event, arg):
    a = arg.translate(FA2EN).strip()
    if not (a.isdigit() and 1 <= int(a) <= 6):
        return await event.edit("مثال: .تقلب 6  (عدد ۱ تا ۶)")
    target, chat = int(a), event.chat_id
    await event.delete()
    for _ in range(12):
        msg = await C().send_message(chat, file=types.InputMediaDice("🎲"))
        if getattr(msg.media, "value", None) == target:
            return
        await asyncio.sleep(1.5)
        await msg.delete()


async def c_action(event, arg):
    chat = event.chat_id
    old = action_tasks.pop(chat, None)
    if old:
        old.cancel()
    parts = arg.translate(FA2EN).split()
    kind = parts[0].lower() if parts else "typing"
    if kind in ("off", "خاموش"):
        return await event.edit("اکشن خاموش شد")
    factories = {
        "typing": types.SendMessageTypingAction, "تایپ": types.SendMessageTypingAction,
        "voice": types.SendMessageRecordAudioAction, "ویس": types.SendMessageRecordAudioAction,
        "video": types.SendMessageRecordVideoAction, "ویدیو": types.SendMessageRecordVideoAction,
        "game": types.SendMessageGamePlayAction, "بازی": types.SendMessageGamePlayAction,
    }
    factory = factories.get(kind)
    if not factory:
        return await event.edit("اکشن‌ها: تایپ | ویس | ویدیو | بازی | off")
    secs = min(int(parts[1]), 600) if len(parts) > 1 and parts[1].isdigit() else 60

    async def loop():
        end = time.time() + secs
        try:
            while time.time() < end:
                await C()(SetTypingRequest(peer=chat, action=factory()))
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await C()(SetTypingRequest(peer=chat, action=types.SendMessageCancelAction()))
            except Exception:  # noqa
                pass

    action_tasks[chat] = asyncio.create_task(loop())
    await event.edit(f"🎬 اکشن «{kind}» برای {secs} ثانیه فعال شد")


def make_logo(text: str, style: int) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1024, 512
    palettes = {1: ((255, 94, 98), (255, 195, 113)), 2: ((67, 206, 162), (24, 90, 157)),
                3: ((142, 45, 226), (74, 0, 224)), 4: ((17, 153, 142), (56, 239, 125)),
                5: ((252, 70, 107), (63, 94, 251))}
    c1, c2 = palettes.get(style, palettes[1])
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    basic = False
    try:  # برای حروف فارسی/عربی
        import arabic_reshaper
        from bidi.algorithm import get_display
        text = get_display(arabic_reshaper.reshape(text))
        basic = True
    except Exception:  # noqa
        pass
    font_path = next((p for p in (
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "DejaVuSans-Bold.ttf"),
        os.path.join(os.environ.get("SELF_REPO_DIR", ""), "fonts", "DejaVuSans-Bold.ttf")) if os.path.isfile(p)),
        "DejaVuSans-Bold.ttf")
    kw = {"layout_engine": ImageFont.Layout.BASIC} if basic else {}
    size = 220
    while True:
        font = ImageFont.truetype(font_path, size, **kw)
        box = d.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= W - 120 or size <= 24:
            break
        size -= 8
    w, h = box[2] - box[0], box[3] - box[1]
    x, y = (W - w) / 2 - box[0], (H - h) / 2 - box[1]
    d.text((x + 5, y + 5), text, font=font, fill=(0, 0, 0))  # سایه
    d.text((x, y), text, font=font, fill=(255, 255, 255))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


async def c_logo(event, arg):
    text, style = arg, 1
    head, _, tail = arg.rpartition(" ")
    if head and tail.isdigit() and 1 <= int(tail) <= 5:
        text, style = head, int(tail)
    if not text.strip():
        return await event.edit("مثال: .لوگو Erfan 3")
    data = await asyncio.get_running_loop().run_in_executor(None, make_logo, text.strip()[:40], style)
    bio = io.BytesIO(data)
    bio.name = "logo.png"
    await C().send_file(event.chat_id, bio)
    await event.delete()


# ───── کامنت اول ─────
async def c_comment(event, arg):
    head, _, rest = arg.partition(" ")
    rest = rest.strip()
    if head in ("add", "اضافه") and rest:
        ent = await C().get_entity(rest)
        CFG["fc_channels"][str(utils.get_peer_id(ent))] = dname(ent)
        F["firstcomment"] = True
        msg = f"🥇 کانال «{dname(ent)}» اضافه شد"
    elif head in ("حذف", "del") and rest:
        ent = await C().get_entity(rest)
        CFG["fc_channels"].pop(str(utils.get_peer_id(ent)), None)
        msg = "حذف شد ✅"
    elif head in ("متن", "text") and rest:
        CFG["fc_text"] = rest
        msg = f"متن کامنت: {rest}"
    elif head in ("on", "روشن", "off", "خاموش"):
        F["firstcomment"] = onoff(head)
        msg = "کامنت اول " + ("روشن شد 🥇" if F["firstcomment"] else "خاموش شد")
    else:
        chans = "\n".join(f"• {n}" for n in CFG["fc_channels"].values()) or "هیچ کانالی نیست"
        msg = f"🥇 کانال‌ها:\n{chans}\n\nمتن: {CFG['fc_text']}"
    save_settings()
    await event.edit(msg)


# ───── کارهای زمان‌بندی‌شده (خودکار) ─────
UNITS = {"s": 1, "ث": 1, "m": 60, "د": 60, "h": 3600, "س": 3600}
MAX_TASKS, MIN_EVERY, MAX_EVERY = 10, 60, 86400
task_next = {}
task_fail = {}


DUR_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(ساعت|دقیقه|ثانیه|hours?|hrs?|minutes?|mins?|seconds?|secs?)", re.I)
DUR_UNIT = {"ساعت": 3600, "دقیقه": 60, "ثانیه": 1, "hour": 3600, "hours": 3600, "hr": 3600, "hrs": 3600,
            "minute": 60, "minutes": 60, "min": 60, "mins": 60, "second": 1, "seconds": 1, "sec": 1, "secs": 1}


def parse_cooldown(text: str):
    """زمان انتظار توی متن بات: «۲ دقیقه و ۳۰ ثانیه» ← 150 (جمع همه‌ی بخش‌ها)؛ نبود ← None."""
    total, found = 0.0, False
    for num, unit in DUR_RE.findall((text or "").translate(FA2EN)):
        total += float(num.replace(",", ".")) * DUR_UNIT[unit.lower()]
        found = True
    return min(int(total), MAX_EVERY) if found and total > 0 else None


async def read_cooldown(chat, after_id, wait=4.0):
    """بعد از ارسال دستور، جواب بات رو می‌خونه و زمان انتظارش رو درمیاره."""
    await asyncio.sleep(wait)
    async for m in C().iter_messages(chat, limit=6, min_id=after_id):
        if m.out:
            continue
        sec = parse_cooldown(m.raw_text or "")
        if sec:
            return sec
    return None


def parse_every(tok: str):
    """'5m' | '30s' | '1h' | '5' (دقیقه) | '۵د' ← ثانیه؛ خارج از بازه ← None."""
    m = re.match(r"^(\d+)\s*([a-zثدس]?)$", (tok or "").translate(FA2EN).lower())
    if not m:
        return None
    sec = int(m.group(1)) * UNITS[m.group(2) or "m"]
    return sec if MIN_EVERY <= sec <= MAX_EVERY else None


def fmt_every(sec: int) -> str:
    if sec % 3600 == 0:
        return f"{sec // 3600} ساعت"
    if sec % 60 == 0:
        return f"{sec // 60} دقیقه"
    return f"{sec} ثانیه"


def task_line(t) -> str:
    kind = "👆 کلیک" if t["kind"] == "click" else "💬 ارسال"
    st = "🟢" if t.get("on", True) else "⏸"
    smart = " 🧠" if t.get("smart") else ""
    return f"{st} #{t['id']} {kind}{smart} «{t['text']}» هر {fmt_every(t['every'])}  (چت {t['chat']})"


async def click_button(chat, text: str) -> bool:
    """روی دکمه‌ای که متنش شامل text باشه (توی ۱۵ پیام آخر) کلیک می‌کنه."""
    want = text.lower()
    async for m in C().iter_messages(chat, limit=15):
        for row in (m.buttons or []):
            for b in row:
                if want in (b.text or "").lower():
                    await b.click()
                    return True
    return False


async def run_task(t):
    if t["kind"] == "click":
        if not await click_button(t["chat"], t["text"]):
            raise RuntimeError("دکمه پیدا نشد")
        return None
    return await C().send_message(t["chat"], t["text"])


async def auto_tick(now=None):
    """یک دور بررسی: کارهایی که وقتشون شده رو اجرا می‌کنه."""
    if not (F["autotask"] and state["authorized"]):
        return
    now = now or time.time()
    for t in list(CFG["autotasks"]):
        if not t.get("on", True):
            continue
        nxt = task_next.setdefault(t["id"], now + 10 + (t["id"] % 5) * 3)
        if now < nxt:
            continue
        task_next[t["id"]] = now + t["every"] + random.uniform(0, min(5, t["every"] * 0.05))
        try:
            sent = await run_task(t)
            task_fail[t["id"]] = 0
            if t.get("smart") and sent is not None:
                cd = await read_cooldown(t["chat"], sent.id)
                if cd:  # بات گفته چقدر صبر کنیم
                    task_next[t["id"]] = now + max(cd + 3, 10)
        except FloodWaitError as e:
            task_next[t["id"]] = now + e.seconds + 5
        except Exception as e:  # noqa
            n = task_fail[t["id"]] = task_fail.get(t["id"], 0) + 1
            log.warning("auto task #%s failed (%s): %r", t["id"], n, e)
            if n >= 5:  # ۵ بار پشت‌سرهم خطا ← خاموش + خبر
                t["on"] = False
                save_settings()
                try:
                    await C().send_message("me", f"⚠️ کار خودکار #{t['id']} ({t['text']}) بعد از ۵ خطا متوقف شد: {e}")
                except Exception:  # noqa
                    pass
        await asyncio.sleep(2)  # فاصله بین کارها


async def auto_loop():
    while True:
        try:
            await auto_tick()
        except Exception as e:  # noqa
            log.exception("auto loop: %s", e)
        await asyncio.sleep(5)


def add_task(chat, kind, text, every, smart=False):
    tasks = CFG["autotasks"]
    tid = max([t["id"] for t in tasks], default=0) + 1
    task = {"id": tid, "chat": chat, "kind": kind, "text": text[:200], "every": every, "on": True}
    if smart:
        task["smart"] = True
    tasks.append(task)
    F["autotask"] = True
    save_settings()
    return tid


AUTO_HELP = (
    "⏲ کارهای زمان‌بندی‌شده\n\n"
    "ارسال دستور: .خودکار افزودن 5m میو\n"
    "حالت هوشمند (زمان انتظار رو از جواب بات می‌خونه): .خودکار هوشمند 5m میو\n"
    "کلیک روی دکمه: .خودکار کلیک 10m ماهیگیری\n"
    "واحد: s ثانیه | m دقیقه | h ساعت (حداقل 1m)\n"
    ".خودکار لیست | توقف N | شروع N | اجرا N | حذف N | پاک"
)


async def c_auto(event, arg):
    head, _, rest = arg.partition(" ")
    head, rest = head.lower(), rest.strip()
    tasks = CFG["autotasks"]
    if head in ("", "لیست", "list"):
        if not tasks:
            return await event.edit("⏲ هیچ کاری ثبت نشده\n\n" + AUTO_HELP)
        return await event.edit("⏲ کارها:\n" + "\n".join(task_line(t) for t in tasks))
    if head in ("افزودن", "add", "کلیک", "click", "هوشمند", "smart"):
        kind = "click" if head in ("کلیک", "click") else "send"
        smart = head in ("هوشمند", "smart")
        tok, _, text = rest.partition(" ")
        sec, text = parse_every(tok), text.strip()
        if not sec or not text:
            return await event.edit(AUTO_HELP)
        if len(tasks) >= MAX_TASKS:
            return await event.edit(f"حداکثر {MAX_TASKS} کار مجازه؛ با .خودکار حذف N پاک کن")
        tid = add_task(event.chat_id, kind, text, sec, smart)
        extra = "\n🧠 اگه بات زمان انتظار بگه، نوبت بعدی همون موقع اجرا می‌شه" if smart else ""
        return await event.edit(f"⏲ کار #{tid} ثبت شد: «{text}» هر {fmt_every(sec)} توی همین چت{extra}")
    if head in ("پاک", "clear"):
        before = len(tasks)
        tasks[:] = [t for t in tasks if t["chat"] != event.chat_id]
        save_settings()
        return await event.edit(f"🧹 {before - len(tasks)} کار این چت پاک شد")
    if head in ("حذف", "del", "delete", "توقف", "stop", "شروع", "start", "اجرا", "run") and rest.translate(FA2EN).isdigit():
        tid = int(rest.translate(FA2EN))
        t = next((x for x in tasks if x["id"] == tid), None)
        if not t:
            return await event.edit("کاری با این شماره نیست؛ .خودکار لیست")
        if head in ("حذف", "del", "delete"):
            tasks.remove(t)
            msg = f"🗑 کار #{tid} حذف شد"
        elif head in ("توقف", "stop"):
            t["on"] = False
            msg = f"⏸ کار #{tid} متوقف شد"
        elif head in ("شروع", "start"):
            t["on"], task_fail[tid] = True, 0
            task_next.pop(tid, None)
            F["autotask"] = True
            msg = f"▶️ کار #{tid} شروع شد"
        else:
            try:
                await run_task(t)
                msg = f"✅ کار #{tid} اجرا شد"
            except Exception as e:  # noqa
                msg = f"⚠️ کار #{tid} خطا داد: {e}"
        save_settings()
        return await event.edit(msg)
    await event.edit(AUTO_HELP)


# ───── نجات خودکار (کلیک روی دکمه‌ی پیام‌های بات) ─────
catch_seen = {}


def find_button(message, word: str):
    want = word.lower()
    for row in (message.buttons or []):
        for b in row:
            if want in (b.text or "").lower():
                return b
    return None


async def on_catch(event):
    if not (F["autocatch"] and state["authorized"]) or extras.is_quiet():
        return
    cfg = CFG["catch"].get(str(event.chat_id))
    m = event.message
    if not cfg or m.out or not m.buttons:
        return
    key = (event.chat_id, m.id)
    n = catch_seen.get(key, 0)
    times = max(1, min(3, int(cfg.get("times", 2))))  # بدون تنظیم = رفتار قدیمی (حداکثر ۲ بار)
    btn = find_button(m, cfg["word"])
    if n >= times or not btn:  # هر پیام حداکثر «times» بار (برای ادیت‌ها)
        return
    catch_seen[key] = n + 1
    while len(catch_seen) > 500:
        catch_seen.pop(next(iter(catch_seen)))
    delay = float(cfg.get("delay", 1.0))
    if isinstance(event, events.MessageEdited.Event):
        delay = max(2.0, delay)  # ادیت‌ها: بذار پیام جا بیفته
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        await btn.click()
        extras.bump("catch")
        if "times" in cfg and times > 1 and n + 1 < times:  # کلیک پشت‌سرهم‌ی سریع (فقط اگه خودت «تعداد» رو تنظیم کردی)
            async def _burst():
                await asyncio.sleep(0.08)
                try:
                    await btn.click()
                except Exception:  # noqa
                    pass
            asyncio.create_task(_burst())
    except Exception as e:  # noqa
        log.warning("auto catch click failed: %r", e)


async def c_catch(event, arg):
    allc, key = CFG["catch"], str(event.chat_id)
    toks = arg.translate(FA2EN).split(maxsplit=1)
    head = toks[0].lower() if toks else ""
    rest = toks[1].strip() if len(toks) > 1 else ""
    if head in ("off", "خاموش"):
        allc.pop(key, None)
        save_settings()
        return await meow.reply(event, "🐈 نجات خودکار این چت خاموش شد")
    if not head:  # بدون آرگومان: روشن/خاموش
        if key in allc:
            allc.pop(key)
            save_settings()
            return await meow.reply(event, "🐈 نجات خودکار این چت خاموش شد 🔴")
    cfg = allc.setdefault(key, {"word": "نجات", "delay": 1.0})
    if head in ("on", "روشن"):
        pass
    elif head in ("کلمه", "word") and rest:
        cfg["word"] = rest
    elif head in ("تاخیر", "تأخیر", "delay"):
        try:
            d = float(rest)
        except ValueError:
            return await meow.reply(event, "مثال: .نجات تاخیر 1.5   (بین 0 تا 10 ثانیه)")
        if not 0 <= d <= 10:
            return await meow.reply(event, "تاخیر باید بین 0 تا 10 ثانیه باشه")
        cfg["delay"] = d
    elif head in ("تعداد", "times"):
        if not rest.isdigit() or not 1 <= int(rest) <= 3:
            return await meow.reply(event, "مثال: .نجات تعداد 2   (تعداد کلیک روی هر پیام/ادیت، بین 1 تا 3)")
        cfg["times"] = int(rest)
    F["autocatch"] = True
    save_settings()
    await meow.reply(
        event,
        f"🐈 نجات خودکار روشنه: دکمه‌ی شامل «{cfg['word']}» با {cfg['delay']:g} ثانیه تأخیر کلیک می‌شه"
        f" (تعداد کلیک: {cfg.get('times', 2)})")


async def c_backup(event, arg):
    data = {"features": F, "cfg": {k: v for k, v in CFG.items() if k not in ("bot_token", "proxy")}}
    bio = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=1).encode())
    bio.name = "self-settings.json"
    await C().send_file("me", bio, caption="💾 پشتیبان تنظیمات سلف (بدون توکن بات و پروکسی)")
    await event.edit("💾 پشتیبان توی Saved Messages ذخیره شد")


async def c_restore(event, arg):
    r = await event.get_reply_message() if event.is_reply else None
    if not r or not r.document or (r.document.size or 0) > 1_000_000:
        return await event.edit("روی فایل پشتیبان (self-settings.json) ریپلای کن")
    try:
        d = json.loads((await r.download_media(file=bytes)).decode())
    except Exception:  # noqa
        return await event.edit("فایل پشتیبان معتبر نیست")
    n = 0
    for k, v in (d.get("features") or {}).items():
        if k in F and isinstance(v, bool):
            F[k], n = v, n + 1
    for k, v in (d.get("cfg") or {}).items():
        if k in CFG and k not in ("bot_token", "proxy") and isinstance(v, type(CFG[k])):
            CFG[k], n = v, n + 1
    save_settings()
    await refresh()
    await event.edit(f"♻️ {n} تنظیم بازیابی شد")


# ───── بروزرسانی با فایل ─────
def update_file_ok(msg) -> bool:
    """فقط فایلی که خودت مستقیم توی Saved Messages آپلود کردی (نه فوروارد، نه چت دیگران)."""
    return bool(msg and msg.out and msg.document and not msg.fwd_from
                and msg.chat_id == state.get("me"))


def _fname(msg) -> str:
    return (getattr(msg.file, "name", None) or "").strip()


async def run_update(msg, reply_to):
    name = _fname(msg)
    if not name.lower().endswith((".zip", ".py")):
        return
    if (msg.document.size or 0) > updater.MAX_ZIP:
        return await reply_to.reply("❌ فایل بیشتر از ۸ مگابایته")
    status = await reply_to.reply("⏳ دارم فایل رو بررسی می‌کنم...")
    tmpdir = tempfile.mkdtemp(prefix="selfdl_")
    try:
        path = await msg.download_media(file=os.path.join(tmpdir, "upload.bin"))
        ok, text = await updater.apply(path, name)
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    if not ok:
        return await safe_edit(status, f"❌ بروزرسانی انجام نشد (هیچ تغییری اعمال نشد)\n{text}")
    await safe_edit(status, text + "\n🔄 در حال ریستارت...")
    await asyncio.sleep(1.5)
    updater.restart()


async def on_update_file(event):
    """حالت خودکار: با روشن بودن کلید «بروزرسانی با فایل»."""
    if ctl.INSTANCE or not (F["update"] and state["authorized"]) or not update_file_ok(event.message):
        return
    if not _fname(event.message).lower().endswith((".zip", ".py")):
        return
    if updater.norm_name(_fname(event.message)) not in updater.ALLOWED and not _fname(event.message).lower().endswith(".zip"):
        return  # یه .py معمولی (مثلاً اسکریپت خودت) رو دست نمی‌زنیم
    await run_update(event.message, event.message)


UPDATE_HELP = (
    "🔄 بروزرسانی با فایل\n\n"
    "• زیپ پروژه یا فایل‌های .py (main, core, features, meow, botpanel) رو توی Saved Messages آپلود کن.\n"
    "• کلید «بروزرسانی با فایل» روشن باشه ← خودکار اعمال می‌شه؛ خاموش باشه ← روی فایل ریپلای کن و بنویس .آپدیت\n"
    "• .آپدیت وضعیت | .آپدیت برگشت | .آپدیت پاک (برگشت به کد GitHub)\n"
    "• اگه نسخه‌ی جدید بالا نیاد خودکار به قبلی برمی‌گرده."
)


async def c_update(event, arg):
    if ctl.INSTANCE:
        return await event.edit("🔒 توی حالت هاب بروزرسانی با فایل فقط برای ادمین هاب و از طریق بات هاب ممکنه")
    head = arg.strip().lower()
    if head in ("وضعیت", "status"):
        return await event.edit(updater.status())
    if head in ("برگشت", "rollback", "undo"):
        msg = updater.restore_prev()
        await event.edit(msg + "\n🔄 در حال ریستارت...")
        await asyncio.sleep(1.5)
        return updater.restart()
    if head in ("پاک", "reset", "clear"):
        msg = updater.reset()
        await event.edit(msg + "\n🔄 در حال ریستارت...")
        await asyncio.sleep(1.5)
        return updater.restart()
    if event.is_reply:
        r = await event.get_reply_message()
        if not update_file_ok(r):
            return await event.edit("❌ فایل باید مستقیم توی Saved Messages خودت آپلود شده باشه (فوروارد یا فایل چت دیگه قبول نیست)")
        if not _fname(r).lower().endswith((".zip", ".py")):
            return await event.edit("❌ فقط .zip یا .py")
        await event.edit("⏳ دارم فایل رو بررسی می‌کنم...")
        return await run_update(r, event)
    await event.edit(UPDATE_HELP + "\n\n" + updater.status())


HANDLERS = {
    "panel": c_panel, "help": c_help, "about": c_about, "ping": c_ping, "time": c_time,
    "date": c_date, "id": c_id, "clock": c_clock, "afk": c_afk, "del": c_del, "type": c_type,
    "calc": c_calc, "format": c_format, "reply": c_reply, "canned": c_canned,
    "guard": c_guard, "lock": c_lock, "unlock": c_unlock, "filter": c_filter, "join": c_join,
    "friend": c_friend, "ignore": c_ignore, "secretary": c_secretary, "react": c_react,
    "mute": c_mute, "unmute": c_unmute, "block": c_block, "unblock": c_unblock, "info": c_info,
    "save": c_save, "download": c_download, "ai": c_ai, "translate": c_translate,
    "anim": c_anim, "cheat": c_cheat, "tts": c_tts, "video": c_video, "news": c_news,
    "music": c_music, "currency": c_currency, "logo": c_logo, "action": c_action,
    "online": c_online, "seen": c_seen, "comment": c_comment, "mentionlog": c_mentionlog,
    "antidel": c_antidel, "backup": c_backup, "restore": c_restore, "status": c_status,
    "auto": c_auto, "meowie": meow.c_automeow, "catch": c_catch,
    "automeow": meow.c_automeow, "autofish": meow.c_autofish, "autofridge": meow.c_autofridge,
    "autobat": meow.c_autobat, "autocat": meow.c_autocat, "show": meow.c_show, "sched": meow.c_sched, "alias": meow.c_alias,
    "proxy": meow.c_proxy, "mstatus": meow.c_mstatus, "report": meow.c_report, "quiet": meow.c_quiet, "update": lambda e, a: c_update(e, a),
}
assert set(ALIASES.values()) == set(HANDLERS), set(ALIASES.values()) ^ set(HANDLERS)


async def commands(event):
    prefix, name = event.pattern_match.group(1), event.pattern_match.group(2).lower()
    if name not in ALIASES or (prefix == "/" and name not in SLASH_OK):
        return
    cmd = ALIASES[name]
    arg = (event.pattern_match.group(3) or "").strip()
    try:
        await HANDLERS[cmd](event, arg)
    except Exception as e:  # noqa
        log.warning("command %s failed: %r", cmd, e)
        await safe_edit(event, f"⚠️ خطا: {type(e).__name__}: {str(e)[:150]}")


# ───────────── رویدادها ─────────────
class SafeDict(dict):
    def __missing__(self, k):
        return "{" + k + "}"


async def do_react(chat, msg_id, emoji):
    if cooled(("rx", chat), 2):
        return
    try:
        await C()(SendReactionRequest(peer=chat, msg_id=msg_id,
                                     reaction=[types.ReactionEmoji(emoticon=emoji)]))
    except Exception:  # noqa
        pass


async def auto_format(event):
    if not (F["format"] and state["authorized"]):
        return
    m = event.message
    txt = m.raw_text or ""
    if not txt or m.media or m.entities or m.fwd_from or txt.startswith(SKIP_PREFIXES):
        return
    if any(t["chat"] == event.chat_id for t in CFG["autotasks"]):
        return  # دستورهای خودکار برای بات‌ها نباید ادیت/فرمت بشن
    if meow.format_guard(event.chat_id, txt):
        return  # چت‌های بازی میویی و پیام‌های زمان‌دار هم همین‌طور
    ent = FMT[CFG["fmt"]](0, len(txt.encode("utf-16-le")) // 2)
    try:
        await event.edit(txt, formatting_entities=[ent])
    except Exception:  # noqa
        pass


async def private_in(event):
    if not state["authorized"]:
        return
    sender = await event.get_sender()
    if getattr(sender, "bot", False) or getattr(sender, "is_self", False):
        return
    uid, m = event.sender_id, event.message
    text = m.raw_text or ""
    ignored = uid in CFG["ignored"]

    if F["antidel"]:
        cache[m.id] = (dname(sender), text, bool(m.media))
        while len(cache) > 2000:
            cache.popitem(last=False)

    chat_cfg = CFG["chats"].get(str(event.chat_id)) or {}
    if F["react"] and chat_cfg.get("react"):
        await do_react(event.chat_id, m.id, chat_cfg["react"])
    if F["friends"] and uid in CFG["friends"] and not cooled(("fr", uid), 3600):
        await do_react(event.chat_id, m.id, "❤️")
    if ignored:
        return
    if F["autoseen"]:
        try:
            await C().send_read_acknowledge(event.chat_id, m)
        except Exception:  # noqa
            pass

    if F["autoreply"] and text:
        low = text.lower()
        for kw, resp in CFG["replies"].items():
            if kw in low and not cooled(("kw", uid, kw), 30):
                await event.reply(resp)
                return

    if F["secretary"] and not cooled(("sec", uid), 6 * 3600):
        now = datetime.now(TZ)
        msg = CFG["secretary_text"].format_map(
            SafeDict(name=dname(sender), date=jalali_long(), time=f"{now:%H:%M}"))
        await event.reply(msg)
        return

    if (F["afk"] or quiet_now()) and not cooled(("afk", uid), 900):
        await event.reply(f"🌙 {CFG['afk_text']}")


async def on_edited(event):
    if not (F["antidel"] and state["authorized"]):
        return
    old = cache.get(event.message.id)
    new = event.message.raw_text or ""
    if old and old[1] != new:
        cache[event.message.id] = (old[0], new, old[2])
        await C().send_message(
            "me", f"✏️ {old[0]} پیامش رو ویرایش کرد:\nقبل: {old[1] or '—'}\nبعد: {new or '—'}")


async def on_deleted(event):
    if not (F["antidel"] and state["authorized"]) or event.chat_id is not None:
        return  # فقط پی‌وی/گروه‌های معمولی (توی سوپرگروه‌ها chat_id داره)
    for mid in event.deleted_ids:
        item = cache.pop(mid, None)
        if item:
            await C().send_message(
                "me", f"🗑 {item[0]} این پیام رو حذف کرد:\n{item[1] or '[مدیا/بدون متن]'}")


async def on_mention(event):
    if not (F["mention"] and state["authorized"]):
        return
    try:
        await C().forward_messages("me", event.message)
    except Exception:  # noqa
        chat = await event.get_chat()
        await C().send_message("me", f"🔔 منشن توی {dname(chat)}:\n{event.raw_text}")


_admin_cache = {}


async def is_admin(chat, uid) -> bool:
    key = (chat, uid)
    hit = _admin_cache.get(key)
    if hit and time.time() - hit[1] < 300:
        return hit[0]
    try:
        p = await C().get_permissions(chat, uid)
        res = bool(p.is_admin or p.is_creator)
    except Exception:  # noqa
        res = False
    _admin_cache[key] = (res, time.time())
    return res


async def is_member(channel, uid) -> bool:
    try:
        await C().get_permissions(channel, uid)
        return True
    except UserNotParticipantError:
        return False
    except Exception:  # noqa
        return True  # اگه نتونستیم چک کنیم، مزاحم نشیم


async def try_delete(event):
    try:
        await event.delete()
    except Exception:  # noqa
        pass


async def on_group(event):
    if not state["authorized"]:
        return
    c = CFG["chats"].get(str(event.chat_id))
    if not c:
        return
    uid, m = event.sender_id, event.message
    if uid is None or uid == state.get("me"):
        return

    if F["mute"] and uid in c.get("muted", []):
        return await try_delete(event)
    if F["react"] and c.get("react"):
        await do_react(event.chat_id, m.id, c["react"])

    reason = None
    t = m.raw_text or ""
    if F["guard"] and c.get("guard") and LINK_RE.search(t):
        reason = "link"
    if not reason and F["locks"] and c.get("locks"):
        reason = lock_violation(m, c["locks"])
    if not reason and F["filter"] and c.get("words"):
        low = t.lower()
        if any(w in low for w in c["words"]):
            reason = "word"
    if reason and not await is_admin(event.chat_id, uid):
        return await try_delete(event)

    if F["forcejoin"] and c.get("join") and not await is_admin(event.chat_id, uid):
        if not await is_member(c["join"], uid):
            await try_delete(event)
            if not cooled(("fj", event.chat_id, uid), 60):
                sender = await event.get_sender()
                await C().send_message(
                    event.chat_id, f"⚠️ {dname(sender)}، برای چت کردن اینجا باید عضو {c['join']} بشی.")


async def on_channel_post(event):
    if not (F["firstcomment"] and state["authorized"]):
        return
    if str(event.chat_id) not in CFG["fc_channels"] or cooled(("fc", event.chat_id), 20):
        return
    try:
        await C().send_message(event.chat_id, CFG["fc_text"], comment_to=event.message.id)
    except Exception as e:  # noqa
        log.warning("first comment failed: %r", e)


def make_client(session: str = "") -> TelegramClient:
    c = TelegramClient(StringSession(session), core.API["id"], core.API["hash"],
                       **meow.proxy_kwargs(CFG.get("proxy") or os.getenv("PROXY", "")))
    c.add_event_handler(commands, events.NewMessage(outgoing=True, pattern=CMD_PATTERN))
    c.add_event_handler(auto_format, events.NewMessage(outgoing=True))
    c.add_event_handler(private_in, events.NewMessage(incoming=True, func=lambda e: e.is_private))
    c.add_event_handler(on_edited, events.MessageEdited(incoming=True, func=lambda e: e.is_private))
    c.add_event_handler(on_deleted, events.MessageDeleted())
    c.add_event_handler(
        on_mention,
        events.NewMessage(incoming=True, func=lambda e: bool(e.mentioned) and not e.is_private))
    c.add_event_handler(
        on_group,
        events.NewMessage(incoming=True, func=lambda e: e.is_group))
    c.add_event_handler(on_catch, events.NewMessage(incoming=True, func=lambda e: bool(e.message.buttons)))
    c.add_event_handler(on_catch, events.MessageEdited(incoming=True, func=lambda e: bool(e.message.buttons)))
    # بازی میویی (meow.py): جواب‌های بات، ادیت‌ها، خفاش و الیاس
    c.add_event_handler(meow.on_incoming, events.NewMessage(incoming=True))
    c.add_event_handler(meow.on_edit, events.MessageEdited(incoming=True))
    c.add_event_handler(meow.on_bat, events.NewMessage(incoming=True))
    c.add_event_handler(meow.on_manual_bat, events.NewMessage(outgoing=True))
    c.add_event_handler(meow.alias_intercept, events.NewMessage(outgoing=True))
    c.add_event_handler(on_update_file, events.NewMessage(
        outgoing=True, func=lambda e: bool(e.message.document)))
    c.add_event_handler(
        on_channel_post,
        events.NewMessage(incoming=True, func=lambda e: e.is_channel and not e.is_group))
    return c
