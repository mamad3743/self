"""قابلیت‌های MeowAce-Self برای سلف:
میو/ماهیگیری/یخچال خودکار (لحظه‌ای و زمان‌دار روی سرور تلگرام)، شکار خفاش، حالت نمایش،
زمانبندی پیام، میانبر دستورات (الیاس)، پروکسی و اطلاعات کامل کاربر/چت.

تنظیمات توی CFG["meow"] ذخیره می‌شن (همون settings.json روی Volume).
"""
import re
import html
import time
import random
import asyncio
import datetime
from urllib.parse import urlparse, parse_qs

from telethon.errors import RPCError, SlowModeWaitError, FloodWaitError
from telethon.tl.types import User, Channel, Chat
from telethon.tl.functions.users import GetFullUserRequest

import core
from core import F, CFG, state, log, save_settings

NUM_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

MEOW_WORDS = ["مع", "میو", "میو میو", "معو"]
FISH_WORDS = ["ماهی", "ماهیگیری"]
FRIDGE_WORDS = ["یخچال میویی", "یخچال"]

# اسم دستورهایی که این ماژول اضافه می‌کنه (features بهشون handler می‌ده)
NAMES = {
    "automeow", "میوخودکار", "autofish", "ماهیگیر", "autofridge", "یخچالی",
    "autobat", "خفاش", "show", "نمایش", "sched", "زمانبندی", "alias", "الیاس", "میانبر",
    "proxy", "پروکسی", "meowstatus", "meowhelp", "بازی",
}
RESERVED = set(NAMES)  # features همه‌ی اسم‌های دستورها رو هم اینجا اضافه می‌کنه (برای ممنوع بودن اسم الیاس)


def num(t) -> str:
    return (t or "").translate(NUM_FA)


def C():
    return core.client


def me_id():
    return state.get("me")


def M() -> dict:
    m = CFG.setdefault("meow", {})
    m.setdefault("show", True)
    m.setdefault("aliases", {})
    m.setdefault("automeow", {})  # {chat: {"type": instant|schedule, "count": 1..90}}
    m.setdefault("autofish", {})  # {chat: {"action": feed|sell|fridge, "type": instant|schedule}}
    m.setdefault("autofridge", {})  # {chat: {"action": sell|feed, "type": instant|schedule}}
    m.setdefault("bat", {})  # {chat: {"on": bool, "delay": 0..115}}
    return m


# ───────────── حالت نمایش (Show Mode) ─────────────
def show_on() -> bool:
    return bool(M().get("show", True))


async def reply(event, text, delete_after=1.0, **kw):
    """نمایش جواب دستور؛ اگه حالت نمایش خاموش باشه چیزی نشون نمی‌ده و خود دستور پاک می‌شه."""
    if show_on():
        try:
            await event.edit(text, **kw)
        except Exception:  # noqa
            pass
        return
    if delete_after > 0:
        await asyncio.sleep(delete_after)
    try:
        await event.delete()
    except Exception:  # noqa
        pass


# ───────────── ارسال امن + منتظر جواب بات ─────────────
_locks = {}
_last_sent = {}
_slow = {}
_reply_w = {}  # (chat, msg_id) -> Future (جواب بات به پیام من)
_edit_w = {}  # (chat, msg_id) -> (Future, need_buttons)


def chat_lock(cid) -> asyncio.Lock:
    return _locks.setdefault(cid, asyncio.Lock())


def _fut():
    return asyncio.get_running_loop().create_future()


async def slowmode(cid) -> int:
    hit = _slow.get(cid)
    if hit and time.time() - hit[1] < 600:
        return hit[0]
    try:
        ent = await C().get_entity(cid)
        v = getattr(ent, "slowmode_seconds", 0) or 0
    except Exception:  # noqa
        v = 0
    _slow[cid] = (v, time.time())
    return v


async def send_safe(cid, text, **kw):
    """ارسال با رعایت اسلو‌مود گروه."""
    sm = await slowmode(cid)
    if sm > 0:
        diff = time.time() - _last_sent.get(cid, 0)
        if diff < sm:
            await asyncio.sleep(sm - diff + random.uniform(1.5, 3.5))
    for _ in range(3):
        try:
            res = await C().send_message(cid, text, **kw)
            _last_sent[cid] = time.time()
            return res
        except SlowModeWaitError as e:
            await asyncio.sleep(e.seconds + random.randint(2, 5))
        except FloodWaitError as e:
            if e.seconds > 120:
                raise
            await asyncio.sleep(e.seconds + 2)
    raise RuntimeError("ارسال پیام ممکن نشد")


async def wait_reply(cid, sent_id, timeout):
    """جواب بات (ریپلای) به پیامی که فرستادیم."""
    fut = _fut()
    _reply_w[(cid, sent_id)] = fut
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        _reply_w.pop((cid, sent_id), None)
    try:  # شاید جواب قبل از ثبت منتظر رسیده باشه
        async for m in C().iter_messages(cid, limit=10, min_id=sent_id):
            if not m.out and m.reply_to_msg_id == sent_id:
                return m
    except Exception:  # noqa
        pass
    return None


async def wait_buttons(cid, msg_id, timeout):
    """منتظر ادیت پیام بات و اومدن دکمه‌ها؛ آخرش پیام فعلی رو می‌گیره."""
    fut = _fut()
    _edit_w[(cid, msg_id)] = (fut, True)
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        try:
            return await C().get_messages(cid, ids=msg_id)
        except Exception:  # noqa
            return None
    finally:
        _edit_w.pop((cid, msg_id), None)


async def click_wait(btn, cid, msg_id, timeout, need_buttons=True, fallback=True):
    """کلیک روی دکمه و منتظر ادیت پیام موندن (منتظر قبل از کلیک ثبت می‌شه تا چیزی از دست نره)."""
    fut = _fut()
    _edit_w[(cid, msg_id)] = (fut, need_buttons)
    try:
        await btn.click()
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            if not fallback:
                return None
            return await C().get_messages(cid, ids=msg_id)
    finally:
        _edit_w.pop((cid, msg_id), None)


def find_btn(msg, kw, skip=()):
    for row in (msg.buttons or []):
        for b in row:
            t = b.text or ""
            if kw in t and not any(s in t for s in skip):
                return b
    return None


def parse_clock_or_text(txt: str):
    """«۴:۳۰» یا «۲ دقیقه و ۳۰ ثانیه» ← ثانیه؛ نبود ← None."""
    t = num(txt)
    mc = re.search(r"(\d+):(\d+)", t)
    if mc:
        return int(mc.group(1)) * 60 + int(mc.group(2))
    mm = re.search(r"(\d+)\s*دقیقه", t)
    sm = re.search(r"(\d+)\s*ثانیه", t)
    m_, s_ = (int(mm.group(1)) if mm else 0), (int(sm.group(1)) if sm else 0)
    return m_ * 60 + s_ if (m_ or s_) else None


# ───────────── زمان‌دار روی سرور تلگرام ─────────────
_recent_sched = {}  # (chat, text) -> expiry؛ پیام‌های زمان‌دار نباید با «حالت متن» ادیت بشن


def format_guard(chat_id, text="") -> bool:
    """True یعنی این پیام مال بازی/زمانبندیه و نباید فرمت (ادیت) بشه."""
    sc, m = str(chat_id), M()
    if any(sc in m[k] for k in ("automeow", "autofish", "autofridge", "bat")) or sc in CFG.get("catch", {}):
        return True
    exp = _recent_sched.get((chat_id, (text or "").strip()))
    return bool(exp and exp > time.time())


async def sched_list(cid):
    # توجه: get_messages بدون limit فقط ۱ پیام برمی‌گردونه؛ limit=None همه‌ی صف رو می‌ده
    try:
        return await C().get_messages(cid, limit=None, scheduled=True)
    except Exception as e:  # noqa
        log.warning("scheduled list failed in %s: %r", cid, e)
        return []


def is_word(m, words) -> bool:
    return (m.raw_text or "").strip() in words


async def clear_sched(cid, words):
    try:
        ids = [m.id for m in await sched_list(cid) if is_word(m, words)]
        if ids:
            await C().delete_messages(cid, ids)
    except Exception as e:  # noqa
        log.warning("clear scheduled failed: %r", e)


async def sched_send(cid, text, ts):
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    await C().send_message(cid, text, schedule=dt)


async def free_slots(cid, existing):
    """صف زمان‌دار تلگرام ۱۰۰ تا جا داره؛ اگه نزدیک پر بود از میوهای اضافه پاک می‌کنیم."""
    if len(existing) < 95:
        return
    meows = [m for m in existing if is_word(m, MEOW_WORDS)]
    ids = [m.id for m in meows[90:]] or [m.id for m in meows[-5:]]
    if ids:
        try:
            await C().delete_messages(cid, ids)
        except Exception:  # noqa
            pass


# ───────────── میو خودکار ─────────────
_main_cd = {}  # (chat) -> کولداون اصلی میو


def meow_mode(cid):
    v = M()["automeow"].get(str(cid)) or {}
    return v.get("type", "off"), min(90, max(1, int(v.get("count", 1) or 1)))


def set_meow(cid, typ, count=1):
    if typ == "off":
        M()["automeow"].pop(str(cid), None)
    else:
        M()["automeow"][str(cid)] = {"type": typ, "count": min(90, max(1, count))}
    save_settings()


def parse_meow_cd(txt):
    t = num(txt)
    if not t or any(k in t for k in ("ماهی", "ماهیا", "خوابن", "قلاب", "طعمه", "یخچال")):
        return None
    return parse_clock_or_text(t)


async def meow_once(cid) -> int:
    """یه میو می‌فرسته؛ ثانیه‌ی نوبت بعدی رو برمی‌گردونه."""
    sent = await send_safe(cid, random.choice(MEOW_WORDS))
    rep = await wait_reply(cid, sent.id, 28)
    if not rep:
        return 60
    txt = rep.raw_text or ""
    cd = parse_meow_cd(txt)
    if cd is None:
        return 255
    if "هنوز میوت نمیاد" not in txt:
        _main_cd[cid] = cd
    return cd


def _buf(cd) -> int:
    return random.randint(4, 9) if cd > 50 else 2


async def meow_loop(cid):
    while True:
        if not (F["automeow"] and meow_mode(cid)[0] == "instant"):
            return
        try:
            async with chat_lock(cid):
                cd = await meow_once(cid)
        except FloodWaitError as e:
            cd = e.seconds + 5
        except Exception as e:  # noqa
            log.warning("automeow %s: %r", cid, e)
            cd = 60
        await asyncio.sleep(cd + _buf(cd))


async def schedule_next_meow(cid, remaining, main_cd, count):
    count = min(90, max(1, count))
    existing = await sched_list(cid)
    mine = sorted((m for m in existing if is_word(m, MEOW_WORDS)), key=lambda m: m.date)
    if len(mine) > 90:
        try:
            await C().delete_messages(cid, [m.id for m in mine[90:]])
        except Exception:  # noqa
            pass
        mine = mine[:90]
    needed = min(count - len(mine), 99 - len(existing))
    if needed <= 0:
        return
    now = time.time()
    if not mine:
        ts = now + remaining + _buf(remaining)
    else:
        ts = max(max(m.date.timestamp() for m in mine) + main_cd + _buf(main_cd), now + remaining + _buf(remaining))
    for _ in range(needed):
        try:
            await sched_send(cid, random.choice(MEOW_WORDS), ts)
        except FloodWaitError as e:
            log.warning("automeow schedule flood %ss", e.seconds)
            break
        except Exception as e:  # noqa
            log.warning("automeow schedule error in %s: %r", cid, e)
            break
        ts += main_cd + _buf(main_cd)
        await asyncio.sleep(0.4)


async def _meow_sched_reply(event):
    cid, txt = event.chat_id, event.raw_text or ""
    cd = parse_meow_cd(txt)
    if cd is None:
        return
    _, count = meow_mode(cid)
    if "هنوز میوت نمیاد" in txt:
        remaining, main = cd, _main_cd.get(cid, 255)
    else:
        _main_cd[cid] = main = remaining = cd
    async with chat_lock(cid):
        await schedule_next_meow(cid, remaining, main, count)


async def meow_kick(cid):
    """شروع/ترمیم زنجیره‌ی زمان‌دار: یه میوی فوری می‌فرسته تا کولداون رو بفهمیم و بقیه رو زمان‌دار می‌کنیم."""
    _, count = meow_mode(cid)
    async with chat_lock(cid):
        have = [m for m in await sched_list(cid) if is_word(m, MEOW_WORDS)]
        if len(have) >= count:
            return
        await send_safe(cid, random.choice(MEOW_WORDS))
    await asyncio.sleep(35)  # on_incoming با جواب بات زنجیره رو ادامه می‌ده
    if not F["automeow"] or meow_mode(cid)[0] != "schedule":
        return
    async with chat_lock(cid):  # بات جواب نداد؟ با زمان پیش‌فرض زمان‌دار کن
        if not [m for m in await sched_list(cid) if is_word(m, MEOW_WORDS)]:
            await schedule_next_meow(cid, 255, _main_cd.get(cid, 255), count)


# ───────────── ماهیگیری خودکار ─────────────
FISH_KW = {"feed": "پیشی", "sell": "فروش", "fridge": "یخچال"}
FISH_LABEL = {"feed": "غذادادن به پیشی 🐱", "sell": "فروش مستقیم ماهی 💰", "fridge": "ذخیره در یخچال 🧊"}


def fish_info(cid) -> dict:
    v = M()["autofish"].get(str(cid))
    if not v:
        return {"active": False, "action": "feed", "type": "off"}
    return {"active": v.get("type") in ("instant", "schedule"), "action": v.get("action", "feed"),
            "type": v.get("type", "instant")}


def set_fish(cid, action, typ):
    if typ == "off":
        M()["autofish"].pop(str(cid), None)
    else:
        M()["autofish"][str(cid)] = {"action": action, "type": typ}
    save_settings()


def parse_fish_cd(txt):
    t = num(txt)
    if not any(k in t for k in ("صبر کنی", "خوابن", "کولداون", "کافیه")):
        return None
    cd = parse_clock_or_text(t)
    return cd if cd is not None else 300


async def fish_act(cid, init, action) -> int:
    """بعد از جواب بات به «ماهی»: دکمه‌ی مناسب رو می‌زنه؛ ثانیه‌ی نوبت بعدی رو برمی‌گردونه."""
    cd = parse_fish_cd(init.raw_text or "")
    if cd is not None:
        return cd + 3
    target = init if init.buttons else await wait_buttons(cid, init.id, 24)
    if not (target and target.buttons):
        return 60
    await asyncio.sleep(random.uniform(0.8, 1.6))
    btn = find_btn(target, FISH_KW.get(action, "پیشی"))
    if btn:
        if action == "fridge":
            f_msg = await click_wait(btn, cid, target.id, 12, need_buttons=False, fallback=False)
            if f_msg and any(k in (f_msg.raw_text or "") for k in ("جا نداره", "پر", "قبل", "موجود", "یخچال")):
                s_btn = find_btn(f_msg, "فروش")  # یخچال پر بود ← جایگزین: فروش
                if s_btn:
                    await asyncio.sleep(1.0)
                    await s_btn.click()
        else:
            await btn.click()
    return 300


async def fish_loop(cid):
    while True:
        info = fish_info(cid)
        if not (F["autofish"] and info["active"] and info["type"] == "instant"):
            return
        try:
            async with chat_lock(cid):
                sent = await send_safe(cid, random.choice(FISH_WORDS))
                init = await wait_reply(cid, sent.id, 20)
                sleep = await fish_act(cid, init, info["action"]) if init else 60
        except FloodWaitError as e:
            sleep = e.seconds + 5
        except Exception as e:  # noqa
            log.warning("autofish %s: %r", cid, e)
            sleep = 60
        await asyncio.sleep(sleep)


async def schedule_next_fish(cid, remaining):
    existing = await sched_list(cid)
    mine = [m for m in existing if is_word(m, FISH_WORDS)]
    now = time.time()
    if remaining > 10 and mine:  # پیام‌هایی که قبل از تموم شدن کولداون زمان‌دار شدن
        bad = [m.id for m in mine if m.date.timestamp() < now + remaining]
        if bad:
            try:
                await C().delete_messages(cid, bad)
            except Exception:  # noqa
                pass
            mine = [m for m in mine if m.id not in bad]
    if mine:
        return
    await free_slots(cid, existing)
    ts = now + remaining + (random.randint(3, 8) if remaining > 10 else 2)
    try:
        await sched_send(cid, random.choice(FISH_WORDS), ts)
    except Exception as e:  # noqa
        log.warning("autofish schedule error in %s: %r", cid, e)


async def _fish_sched_reply(event):
    cid = event.chat_id
    info = fish_info(cid)
    async with chat_lock(cid):
        sleep = await fish_act(cid, event.message, info["action"])
        await schedule_next_fish(cid, sleep)


async def fish_kick(cid):
    async with chat_lock(cid):
        await schedule_next_fish(cid, 4)


# ───────────── یخچال خودکار ─────────────
FRIDGE_LABEL = {"sell": "پخت ماهی خام و فروش پخته‌ها 💰", "feed": "پخت ماهی خام و غذادادن به پیشی 🐱"}


def fridge_info(cid) -> dict:
    v = M()["autofridge"].get(str(cid))
    if not v:
        return {"active": False, "action": "sell", "type": "off"}
    return {"active": v.get("type") in ("instant", "schedule"), "action": v.get("action", "sell"),
            "type": v.get("type", "instant")}


def set_fridge(cid, action, typ):
    if typ == "off":
        M()["autofridge"].pop(str(cid), None)
    else:
        M()["autofridge"][str(cid)] = {"action": action, "type": typ}
    save_settings()


async def fridge_process(cid, fridge_msg, action) -> int:
    """پیام یخچال رو ماهی‌به‌ماهی پیمایش می‌کنه (پخت یا فروش/غذا)؛ ثانیه‌ی نوبت بعدی رو برمی‌گردونه."""
    for _ in range(40):  # سقف تعداد ماهی توی یک دور (جلوگیری از حلقه‌ی بی‌پایان)
        latest = await C().get_messages(cid, ids=fridge_msg.id)
        if not latest or not latest.buttons:
            return 1800
        first = next((b for row in latest.buttons for b in row if "ارتقا" not in (b.text or "")), None)
        if not first:
            return 1800
        await asyncio.sleep(1.8)
        menu = await click_wait(first, cid, fridge_msg.id, 8)
        if not menu or not menu.buttons:
            return 1800
        txt = num(menu.raw_text or "")
        cook_btn = act_btn = None
        for row in menu.buttons:
            for b in row:
                t = b.text or ""
                if "بپوخش" in t:
                    cook_btn = b
                elif "فروش" in t and action == "sell":
                    act_btn = b
                elif "پیشی" in t and action == "feed":
                    act_btn = b
        if "پخته شده" in txt or (act_btn and not cook_btn):
            if not act_btn:
                return 1800
            await asyncio.sleep(2.0)
            act_msg = await click_wait(act_btn, cid, fridge_msg.id, 6)
            if act_msg and act_msg.buttons:
                await asyncio.sleep(1.8)
                await act_msg.buttons[0][0].click()
                await asyncio.sleep(1.8)
            continue  # ماهی بعدی
        if cook_btn:
            await asyncio.sleep(2.0)
            confirm = await click_wait(cook_btn, cid, fridge_msg.id, 6)
            if confirm and confirm.buttons:
                c_txt = num(confirm.raw_text or "")
                m = (re.search(r"زمان\s*مورد\s*نیاز\s*پخیدن\s*:\s*(\d+):(\d+)", c_txt)
                     or re.search(r"(\d+):(\d+)", c_txt))
                cook_sec = int(m.group(1)) * 60 + int(m.group(2)) if m else 180
                await asyncio.sleep(2.0)
                await confirm.buttons[0][0].click()
                return cook_sec + 60
            return 120
        return 1800
    return 1800


async def fridge_loop(cid):
    while True:
        info = fridge_info(cid)
        if not (F["autofridge"] and info["active"] and info["type"] == "instant"):
            return
        try:
            async with chat_lock(cid):
                sent = await send_safe(cid, "یخچال میویی")
                msg = await wait_reply(cid, sent.id, 20)
                sleep = await fridge_process(cid, msg, info["action"]) if msg else 60
        except FloodWaitError as e:
            sleep = e.seconds + 5
        except Exception as e:  # noqa
            log.warning("autofridge %s: %r", cid, e)
            sleep = 60
        await asyncio.sleep(max(sleep, 30))


async def schedule_next_fridge(cid, remaining):
    existing = await sched_list(cid)
    mine = [m for m in existing if is_word(m, FRIDGE_WORDS)]
    now = time.time()
    if remaining > 10 and mine:
        bad = [m.id for m in mine if m.date.timestamp() < now + remaining]
        if bad:
            try:
                await C().delete_messages(cid, bad)
            except Exception:  # noqa
                pass
            mine = [m for m in mine if m.id not in bad]
    if mine:
        return
    await free_slots(cid, existing)
    ts = now + remaining + (random.randint(3, 8) if remaining > 10 else 2)
    try:
        await sched_send(cid, "یخچال میویی", ts)
    except Exception as e:  # noqa
        log.warning("autofridge schedule error in %s: %r", cid, e)


async def _fridge_sched_reply(event):
    cid = event.chat_id
    info = fridge_info(cid)
    async with chat_lock(cid):
        sleep = await fridge_process(cid, event.message, info["action"])
        await schedule_next_fridge(cid, sleep)


async def fridge_kick(cid):
    async with chat_lock(cid):
        await schedule_next_fridge(cid, 4)


# ───────────── شکار خفاش ─────────────
BAT_EMOJI = {
    1: "✨", 2: "🧄", 3: "👀", 4: "👶", 5: "💦", 6: "👾", 7: "🌦", 8: "💨", 9: "⚫️", 10: "🕷",
    11: "🧼", 12: "🐥", 13: "💙", 14: "💙", 15: "🙍‍♀️", 16: "🧽", 17: "🌹", 18: "🤖", 19: "💥",
    20: "🍋", 21: "🎭", 22: "🗻", 23: "🪞", 24: "🃏", 25: "❤️", 26: "🚒", 27: "🌕", 28: "🧛",
    29: "🧊", 30: "😇", 31: "😈", 32: "🔥", 33: "🇫🇷", 34: "⭐️", 35: "🌧", 36: "🪙", 37: "⚡️", 38: "🌑",
}
_bat_seen = set()


def _norm_bat(txt: str) -> str:
    return num(txt).replace("ك", "ک").replace("ي", "ی").replace("ى", "ی")


def parse_bat_code(txt):
    m = re.search(r"کد[^0-9]{0,10}([0-9]{1,3})", _norm_bat(txt))
    return int(m.group(1)) if m else None


def is_bat_message(txt) -> bool:
    t = _norm_bat(txt)
    return "خفاش" in t and "کد" in t


async def on_bat(event):
    """خفاش‌های بازی رو خودکار با ایموجی درست ریپلای می‌کنه."""
    if not (F["autobat"] and state.get("authorized")) or event.out:
        return
    cfg = M()["bat"].get(str(event.chat_id))
    if not cfg or not cfg.get("on"):
        return
    txt = event.raw_text or ""
    if not is_bat_message(txt):
        return
    key = (event.chat_id, event.id)
    if key in _bat_seen:
        return
    code = parse_bat_code(txt)
    emoji = BAT_EMOJI.get(code)
    if not emoji:
        log.info("autobat: کد ناشناخته %s", code)
        return
    _bat_seen.add(key)
    if len(_bat_seen) > 500:
        _bat_seen.clear()
    d = cfg.get("delay", 1)
    if d > 0:
        await asyncio.sleep(d)
    try:
        await C().send_message(event.chat_id, emoji, reply_to=event.id)
    except Exception as e:  # noqa
        log.warning("autobat send failed: %r", e)


async def on_manual_bat(event):
    """حالت دستی: روی پیام خفاش ریپلای کن و بنویس batt ← پیامت پاک می‌شه و ایموجی درست می‌ره."""
    if not state.get("authorized"):
        return
    raw = (event.raw_text or "").strip()
    if raw.lower().lstrip("/.=!").strip() != "batt":
        return
    reply_id = event.reply_to_msg_id
    if not reply_id:
        return
    try:
        target = await event.get_reply_message() or await C().get_messages(event.chat_id, ids=reply_id)
    except Exception:  # noqa
        return
    code = parse_bat_code((target.raw_text if target else "") or "")
    if code is None:
        return  # روی پیام غیرخفاش ریپلای شده؛ پیام رو نگه می‌داریم
    try:
        await event.delete()
    except Exception:  # noqa
        pass
    emoji = BAT_EMOJI.get(code)
    if emoji:
        try:
            await C().send_message(event.chat_id, emoji, reply_to=reply_id)
        except Exception as e:  # noqa
            log.warning("manual bat failed: %r", e)


# ───────────── مدیریت حلقه‌ها و ترمیم زنجیره‌ها ─────────────
LOOPS = {"meow": meow_loop, "fish": fish_loop, "fridge": fridge_loop}
KICKS = {"meow": meow_kick, "fish": fish_kick, "fridge": fridge_kick}
SCHED_REPLY = {"meow": _meow_sched_reply, "fish": _fish_sched_reply, "fridge": _fridge_sched_reply}
# kind: (کلید قابلیت، کلید تنظیمات، کلمه‌ها، مهلت بدون پیام زمان‌دار قبل از ترمیم)
CHAINS = {
    "meow": ("automeow", "automeow", MEOW_WORDS, 300),
    "fish": ("autofish", "autofish", FISH_WORDS, 420),
    "fridge": ("autofridge", "autofridge", FRIDGE_WORDS, 900),
}
TASKS = {}
_empty = {}
_last_watch = 0.0


def _desired():
    out = set()
    if not state.get("authorized") or core.client is None:
        return out
    for kind, (feat, field, _w, _g) in CHAINS.items():
        if F.get(feat):
            for cid, v in M()[field].items():
                if v.get("type") == "instant":
                    out.add((kind, int(cid)))
    return out


async def _watch_chains():
    """اگه صف زمان‌دار یه چت (حالت schedule) بیش از حد خالی بمونه، زنجیره رو دوباره راه می‌ندازه."""
    global _last_watch
    now = time.time()
    if now - _last_watch < 120:
        return
    _last_watch = now
    for kind, (feat, field, words, grace) in CHAINS.items():
        if not F.get(feat):
            continue
        for cid_s, v in list(M()[field].items()):
            if v.get("type") != "schedule":
                continue
            cid, key = int(cid_s), (kind, int(cid_s))
            if chat_lock(cid).locked():
                continue
            if [m for m in await sched_list(cid) if is_word(m, words)]:
                _empty.pop(key, None)
                continue
            if now - _empty.setdefault(key, now) >= grace:
                _empty.pop(key, None)
                log.info("%s: صف زمان‌دار چت %s خالیه؛ ترمیم زنجیره", kind, cid)
                asyncio.create_task(KICKS[kind](cid))


async def ensure():
    """حلقه‌های لحظه‌ای رو با تنظیمات فعلی هماهنگ می‌کنه (شروع/توقف)."""
    want = _desired()
    for key in list(TASKS):
        if key not in want or TASKS[key].done():
            TASKS.pop(key).cancel()
    for key in want - set(TASKS):
        TASKS[key] = asyncio.create_task(LOOPS[key[0]](key[1]))


async def supervisor():
    while True:
        try:
            await ensure()
            if state.get("authorized"):
                await _watch_chains()
        except Exception as e:  # noqa
            log.exception("meow supervisor: %s", e)
        await asyncio.sleep(30)


# ───────────── رویدادها ─────────────
async def on_incoming(event):
    """جواب‌های بات: آزاد کردن منتظرها + ادامه‌ی زنجیره‌ی حالت زمان‌دار."""
    if not state.get("authorized"):
        return
    rid = event.reply_to_msg_id
    if not rid:
        return
    cid = event.chat_id
    fut = _reply_w.get((cid, rid))
    if fut and not fut.done():
        fut.set_result(event.message)
    sc, m = str(cid), M()
    kinds = [k for k, (feat, field, _w, _g) in CHAINS.items()
             if F.get(feat) and (m[field].get(sc) or {}).get("type") == "schedule"]
    if not kinds:
        return
    try:
        rep = await event.get_reply_message()
    except Exception:  # noqa
        return
    if not rep or rep.sender_id != me_id():
        return
    txt = (rep.raw_text or "").strip()
    for k in kinds:
        if txt in CHAINS[k][2]:
            asyncio.create_task(_guarded(SCHED_REPLY[k], event))


async def _guarded(fn, event):
    try:
        await fn(event)
    except Exception as e:  # noqa
        log.warning("meow chain %s failed: %r", getattr(fn, "__name__", fn), e)


async def on_edit(event):
    entry = _edit_w.get((event.chat_id, event.message.id))
    if not entry:
        return
    fut, need = entry
    if not fut.done() and (not need or event.message.buttons):
        fut.set_result(event.message)


# ───────────── میانبر دستورات (الیاس) ─────────────
_alias_ids = set()
_alias_times = []


def _norm_alias(name: str) -> str:
    return (name or "").strip().lstrip("/.").lower()


def _head(text: str) -> str:
    return ((text or "").strip().split() or [""])[0].lstrip("/.").lower()


def add_alias(name, target):
    name, target = _norm_alias(name), (target or "").strip()
    al = M()["aliases"]
    if not name or not target or any(c.isspace() for c in name):
        return False, "نام الیاس یا دستور مقصد خالیه (نام نباید فاصله داشته باشه)"
    if name in RESERVED:
        return False, f"«{name}» اسم یکی از دستورهای خود سلفه؛ یه اسم دیگه بده"
    for part in (p.strip() for p in target.split("&&") if p.strip()):
        h = _head(part)
        if h == name or h in al:
            return False, "الیاس نمی‌تونه الیاس دیگه‌ای (یا خودش) رو صدا بزنه"
    if len(al) >= 50 and name not in al:
        return False, "حداکثر ۵۰ الیاس مجازه"
    al[name] = target
    save_settings()
    return True, f"✅ الیاس `{name}` برای `{target}` ثبت شد"


def resolve_alias(raw: str):
    """ماکرو: $1 $2 ... آرگومان‌ها، $* همه‌ی آرگومان‌ها، && زنجیره‌ی دستورها (حداکثر ۵)."""
    s = (raw or "").strip()
    al = M()["aliases"]
    if not s or not al:
        return []
    m = re.match(r"^(?:[/.])?([^\s]+)(?:\s+(.*))?$", s, re.DOTALL)
    if not m or m.group(1).lower() not in al:
        return []
    rest = m.group(2) or ""
    args = rest.split()
    out = []
    for chunk in [c.strip() for c in al[m.group(1).lower()].split("&&") if c.strip()][:5]:
        cmd = chunk
        if re.search(r"\$(?:\d+|\*)", cmd):
            for i, val in enumerate(args, 1):
                cmd = cmd.replace(f"${i}", val)
            cmd = re.sub(r"\$\d+", "", cmd.replace("$*", rest)).strip()
        elif rest:
            cmd = f"{cmd} {rest}"
        if cmd.strip():
            out.append(cmd.strip())
    return out


async def alias_intercept(event):
    if not state.get("authorized") or not M()["aliases"] or event.message.media:
        return
    if event.id in _alias_ids:
        _alias_ids.discard(event.id)
        return
    raw = event.raw_text or ""
    if raw.strip().lower().lstrip("/.=!") == "batt":
        return
    if raw.lstrip().startswith(".") and _head(raw) in RESERVED:
        return  # دستور خود سلفه
    cmds = resolve_alias(raw)
    if not cmds:
        return
    now = time.time()
    _alias_times[:] = [t for t in _alias_times if now - t < 60]
    if len(_alias_times) >= 20:  # ترمز ایمنی (جلوگیری از حلقه/اسپم)
        return
    _alias_times.append(now)
    for c in cmds:
        try:
            sent = await C().send_message(event.chat_id, c, reply_to=event.reply_to_msg_id)
            _alias_ids.add(sent.id)
            if len(_alias_ids) > 1000:
                _alias_ids.clear()
        except Exception as e:  # noqa
            log.warning("alias send failed: %r", e)
            break
        await asyncio.sleep(0.4)
    if not show_on():
        try:
            await event.delete()
        except Exception:  # noqa
            pass


# ───────────── پروکسی ─────────────
def parse_proxy_link(link: str) -> dict:
    """tg://proxy · tg://socks · t.me/proxy · socks5://user:pass@host:port · http://host:port"""
    link = (link or "").strip()
    if not link:
        return {}
    low = link.lower()
    if "tg://proxy" in low or "t.me/proxy" in low:
        qs = parse_qs(urlparse(link).query)
        server, port = qs.get("server", [""])[0], qs.get("port", ["443"])[0]
        if server:
            return {"type": "mtproto", "host": server, "port": int(port) if port.isdigit() else 443,
                    "secret": qs.get("secret", [""])[0]}
    if "tg://socks" in low or "t.me/socks" in low:
        qs = parse_qs(urlparse(link).query)
        server, port = qs.get("server", [""])[0], qs.get("port", ["1080"])[0]
        if server:
            return {"type": "socks5", "host": server, "port": int(port) if port.isdigit() else 1080,
                    "username": qs.get("user", [""])[0] or None, "password": qs.get("pass", [""])[0] or None}
    for proto in ("socks5://", "socks5h://", "socks4://", "socks://", "http://", "https://"):
        if low.startswith(proto):
            p = urlparse(link)
            typ = "socks4" if p.scheme == "socks4" else ("socks5" if "socks" in p.scheme else "http")
            return {"type": typ, "host": p.hostname or "127.0.0.1",
                    "port": p.port or (8080 if typ == "http" else 1080),
                    "username": p.username, "password": p.password}
    return {}


def mask_proxy(link: str) -> str:
    d = parse_proxy_link(link)
    if not d:
        return "نامعتبر"
    auth = " (با رمز)" if d.get("password") or d.get("secret") else ""
    return f"{d['type']} {d['host']}:{d['port']}{auth}"


def proxy_kwargs(link: str) -> dict:
    """آرگومان‌های پروکسی برای TelegramClient (خالی = بدون پروکسی)."""
    d = parse_proxy_link(link)
    if not d:
        return {}
    typ, host, port = d["type"], d["host"], d["port"]
    if typ == "mtproto":
        from telethon.network.connection import (
            ConnectionTcpMTProxyIntermediate, ConnectionTcpMTProxyRandomizedIntermediate)
        sec = (d.get("secret") or "").strip()
        if not sec:
            log.warning("پروکسی MTProto بدون secret کار نمی‌کنه؛ نادیده گرفته شد")
            return {}
        rnd = sec.lower().startswith(("dd", "ee")) or len(sec) > 32
        cls = ConnectionTcpMTProxyRandomizedIntermediate if rnd else ConnectionTcpMTProxyIntermediate
        return {"connection": cls, "proxy": (host, port, sec)}
    try:
        import socks
        pt = {"socks5": socks.SOCKS5, "socks4": socks.SOCKS4, "http": socks.HTTP}[typ]
    except ImportError:
        pt = typ
    log.info("پروکسی فعال: %s", mask_proxy(link))
    return {"proxy": (pt, host, port, True, d.get("username"), d.get("password"))}


# ───────────── اطلاعات کاربر/چت (HTML امن) ─────────────
def _type_str(e) -> str:
    if isinstance(e, User):
        return "🤖 ربات" if getattr(e, "bot", False) else "👤 کاربر"
    if isinstance(e, Channel):
        return "📢 کانال" if getattr(e, "broadcast", False) else "👥 سوپرگروه"
    if isinstance(e, Chat):
        return "👥 گروه معمولی"
    return "ناشناس"


def _full_name(e) -> str:
    n = " ".join(x for x in (getattr(e, "first_name", None), getattr(e, "last_name", None)) if x)
    return n or getattr(e, "title", None) or "بدون نام"


async def info_report(client, event, arg=""):
    """(متن HTML، entity). هدف: آرگومان (یوزرنیم/آیدی/لینک) ← ریپلای ← فوروارد ← طرف پی‌وی ← خودت."""
    E = html.escape
    reply_msg = await event.get_reply_message() if event.is_reply else None
    target = fwd_ent = fwd_hidden = None
    is_fwd = False
    arg = (arg or "").strip()

    if arg:
        a = arg.split("t.me/")[-1].strip("/") if "t.me/" in arg else arg
        a = a.lstrip("@")
        try:
            target = await client.get_entity(int(a) if a.lstrip("-").isdigit() else a)
        except Exception as e:  # noqa
            return f"❌ کاربر یا چتی با «{E(arg)}» پیدا نشد.\nعلت: {E(str(e)[:120])}", None
    elif reply_msg:
        fwd = getattr(reply_msg, "fwd_from", None)
        if fwd:
            is_fwd = True
            if getattr(fwd, "from_id", None):
                try:
                    fwd_ent = await client.get_entity(fwd.from_id)
                except Exception:  # noqa
                    fwd_ent = fwd.from_id
            elif getattr(fwd, "from_name", None):
                fwd_hidden = fwd.from_name
        try:
            target = await reply_msg.get_sender()
        except Exception:  # noqa
            target = None
    elif event.is_private:
        try:
            target = await event.get_chat()
        except Exception:  # noqa
            target = None
    if target is None and not fwd_hidden:
        target = await client.get_me()

    lines = ["🔍 <b>اطلاعات شناسایی</b>", ""]
    if isinstance(target, (User, Channel, Chat)):
        lines.append(f"• <b>نام:</b> {E(_full_name(target))}")
        uname = getattr(target, "username", None)
        lines.append(f"• <b>یوزرنیم:</b> {'@' + E(uname) if uname else 'ندارد'}")
        lines.append(f"• <b>آیدی عددی:</b> <code>{target.id}</code>")
        lines.append(f"• <b>نوع:</b> {_type_str(target)}")
        photo = getattr(target, "photo", None)
        lines.append(f"• <b>دیتاسنتر:</b> <code>{getattr(photo, 'dc_id', None) or 'نامشخص'}</code>")
        if isinstance(target, User):
            if getattr(target, "premium", False):
                lines.append("• <b>پریمیوم:</b> ⭐")
            lines.append(f'• <b>پروفایل:</b> <a href="tg://user?id={target.id}">لینک</a>')
        if getattr(target, "verified", False):
            lines.append("• <b>تأییدشده:</b> 🔵")
        if getattr(target, "scam", False):
            lines.append("• ⚠️ <b>برچسب اسکم دارد</b>")
        if isinstance(target, User):
            try:
                fu = (await client(GetFullUserRequest(target))).full_user
                if getattr(fu, "about", None):
                    lines.append(f"• <b>بیو:</b> {E(fu.about)}")
                if getattr(fu, "common_chats_count", None) is not None:
                    lines.append(f"• <b>گروه مشترک:</b> {fu.common_chats_count}")
            except Exception:  # noqa
                pass
    elif target is not None:
        lines.append(f"• <b>آیدی:</b> <code>{E(str(target))}</code>")

    if is_fwd:
        lines += ["", "📨 <b>منبع فوروارد</b>"]
        if isinstance(fwd_ent, (User, Channel, Chat)):
            lines.append(f"• <b>فرستنده‌ی اصلی:</b> {E(_full_name(fwd_ent))}")
            if getattr(fwd_ent, "username", None):
                lines.append(f"• <b>یوزرنیم:</b> @{E(fwd_ent.username)}")
            lines.append(f"• <b>آیدی:</b> <code>{fwd_ent.id}</code> ({_type_str(fwd_ent)})")
        elif fwd_hidden:
            lines.append(f"• <b>نام مخفی:</b> {E(fwd_hidden)}")
            lines.append("• آیدی: 🔒 با تنظیمات حریم خصوصی فرستنده مخفی شده")
        elif fwd_ent is not None:
            lines.append(f"• <b>شناسه:</b> <code>{E(str(fwd_ent))}</code>")
    elif fwd_hidden:
        lines.append(f"• <b>نام مخفی:</b> {E(fwd_hidden)}")

    lines += ["", f"📍 <b>چت فعلی:</b> <code>{event.chat_id}</code>"]
    if reply_msg:
        lines.append(f"• <b>آیدی پیام ریپلای‌شده:</b> <code>{reply_msg.id}</code>")
    return "\n".join(lines), target


# ───────────── وضعیت این چت ─────────────
def status_text(cid) -> str:
    sc, m = str(cid), M()
    mt, mc = meow_mode(cid)
    meow = {"instant": "🟢 فعال (لحظه‌ای ⚡)", "schedule": f"🟢 فعال (زمان‌دار 📅 — {mc} پیام)"}.get(mt, "🔴 خاموش")

    def line(info, labels):
        if not info["active"]:
            return "🔴 خاموش"
        kind = "لحظه‌ای ⚡" if info["type"] == "instant" else "زمان‌دار 📅"
        return f"🟢 فعال ({kind} — {labels.get(info['action'], info['action'])})"

    c = CFG.get("catch", {}).get(sc)
    catch = (f"🟢 فعال (کلمه: {c.get('word', 'نجات')} · تأخیر: {c.get('delay', 1.0):g}s · "
             f"تعداد: {c.get('times', 2)})") if c else "🔴 خاموش"
    b = m["bat"].get(sc)
    bat = f"🟢 فعال (تأخیر: {b.get('delay', 1)}s)" if b and b.get("on") else "🔴 خاموش"
    master = [k for k in ("automeow", "autofish", "autofridge", "autocatch", "autobat") if not F.get(k)]
    warn = ("\n\n⚠️ کلید کلی این قابلیت‌ها توی پنل خاموشه: " + "، ".join(master)) if master else ""
    return (
        "🐾 **وضعیت بازی میویی توی این چت**\n\n"
        f"📍 چت: `{cid}`\n\n"
        f"🐱 میو خودکار: {meow}\n"
        f"🎣 ماهیگیری خودکار: {line(fish_info(cid), FISH_LABEL)}\n"
        f"🧊 یخچال خودکار: {line(fridge_info(cid), FRIDGE_LABEL)}\n"
        f"🐈 نجات خودکار: {catch}\n"
        f"🦇 شکار خفاش: {bat}\n"
        f"👁 حالت نمایش: {'🟢 روشن' if show_on() else '🔴 خاموش'}"
        + warn
    )


# ───────────── دستورها ─────────────
async def _enable(feat):
    F[feat] = True
    save_settings()
    await ensure()


HELP_MEOW = (
    "🐱 **میو خودکار**\n\n"
    "▸ `.automeow instant` ← لحظه‌ای ⚡\n"
    "▸ `.automeow schedule 5` ← زمان‌دار روی سرور تلگرام (۱ تا ۹۰ پیام؛ اکانت آنلاین نمی‌شه 🛡️)\n"
    "▸ `.automeow off` ← خاموش\n"
    "(فارسی: `.میوخودکار`  ·  می‌تونی `/automeow` هم بزنی)"
)
HELP_FISH = (
    "🎣 **ماهیگیری خودکار**\n\n"
    "▸ `.autofish feed schedule` ← زمان‌دار + غذا به پیشی\n"
    "▸ `.autofish sell schedule` ← زمان‌دار + فروش مستقیم\n"
    "▸ `.autofish fridge schedule` ← زمان‌دار + ذخیره در یخچال (پر بود ← فروش)\n"
    "▸ `.autofish feed|sell|fridge instant` ← لحظه‌ای ⚡\n"
    "▸ `.autofish off` ← خاموش\n"
    "(فارسی: `.ماهیگیر`)"
)
HELP_FRIDGE = (
    "🧊 **یخچال خودکار**\n\n"
    "▸ `.autofridge sell schedule` ← پخت و فروش زمان‌دار\n"
    "▸ `.autofridge feed schedule` ← پخت و غذا به پیشی زمان‌دار\n"
    "▸ `.autofridge sell|feed instant` ← لحظه‌ای ⚡\n"
    "▸ `.autofridge off` ← خاموش\n"
    "(فارسی: `.یخچالی`)"
)
HELP_BAT = (
    "🦇 **شکار خفاش**\n\n"
    "▸ `.autobat on` / `.autobat off` ← خودکار توی این چت\n"
    "▸ `.autobat delay 2` ← تأخیر ارسال ایموجی (۰ تا ۱۱۵ ثانیه)\n"
    "▸ `.autobat list` ← جدول کد ← ایموجی\n"
    "✋ دستی: روی پیام خفاش ریپلای کن و بنویس `batt`\n"
    "(فارسی: `.خفاش`)"
)


async def c_automeow(event, arg):
    cid = event.chat_id
    toks = num(arg).lower().split()
    mt, mc = meow_mode(cid)
    if not toks:
        cur = {"instant": "لحظه‌ای ⚡", "schedule": f"زمان‌دار 📅 ({mc} پیام)"}.get(mt, "خاموش 🔴")
        return await reply(event, f"{HELP_MEOW}\n\nوضعیت این چت: {cur}")
    cmd = toks[0]
    if cmd in ("instant", "on", "زنده", "فوری"):
        await clear_sched(cid, MEOW_WORDS)
        set_meow(cid, "instant")
        await _enable("automeow")
        return await reply(event, "🐱 میو خودکار (لحظه‌ای ⚡) روشن شد 🟢")
    if cmd in ("schedule", "sched", "زمان‌دار", "زماندار"):
        n = int(toks[1]) if len(toks) > 1 and toks[1].isdigit() else 1
        n = max(1, min(90, n))
        set_meow(cid, "schedule", n)
        await _enable("automeow")
        asyncio.create_task(_guarded(lambda e: meow_kick(cid), event))
        return await reply(
            event, f"🐱 میو خودکار (زمان‌دار 📅 — {n} پیام) روشن شد 🟢\nℹ️ یه میوی اولیه می‌فرستم تا کولداون رو بفهمم.")
    if cmd in ("off", "خاموش"):
        await clear_sched(cid, MEOW_WORDS)
        set_meow(cid, "off")
        await ensure()
        return await reply(event, "🐱 میو خودکار این چت خاموش شد 🔴")
    await reply(event, HELP_MEOW)


def _parse_game_args(toks, actions):
    action = typ = None
    off = False
    for t in toks:
        if t in ("off", "خاموش"):
            off = True
        elif t in actions:
            action = actions[t]
        elif t in ("instant", "live", "on", "زنده", "فوری"):
            typ = "instant"
        elif t in ("schedule", "sched", "زمان‌دار", "زماندار"):
            typ = "schedule"
    return action, typ, off


async def c_autofish(event, arg):
    cid = event.chat_id
    toks = num(arg).lower().split()
    info = fish_info(cid)
    if not toks:
        cur = (f"{'لحظه‌ای ⚡' if info['type'] == 'instant' else 'زمان‌دار 📅'} — {FISH_LABEL[info['action']]}"
               if info["active"] else "خاموش 🔴")
        return await reply(event, f"{HELP_FISH}\n\nوضعیت این چت: {cur}")
    action, typ, off = _parse_game_args(toks, {"feed": "feed", "cat": "feed", "sell": "sell", "fridge": "fridge"})
    if off:
        await clear_sched(cid, FISH_WORDS)
        set_fish(cid, "feed", "off")
        await ensure()
        return await reply(event, "🎣 ماهیگیری خودکار این چت خاموش شد 🔴")
    action = action or (info["action"] if info["active"] else "feed")
    typ = typ or "instant"
    await clear_sched(cid, FISH_WORDS)
    set_fish(cid, action, typ)
    await _enable("autofish")
    if typ == "schedule":
        asyncio.create_task(_guarded(lambda e: fish_kick(cid), event))
    await reply(event, f"🎣 ماهیگیری خودکار ({'لحظه‌ای ⚡' if typ == 'instant' else 'زمان‌دار 📅'}) روشن شد 🟢\n"
                       f"▸ عملکرد: {FISH_LABEL[action]}")


async def c_autofridge(event, arg):
    cid = event.chat_id
    toks = num(arg).lower().split()
    info = fridge_info(cid)
    if not toks:
        cur = (f"{'لحظه‌ای ⚡' if info['type'] == 'instant' else 'زمان‌دار 📅'} — {FRIDGE_LABEL[info['action']]}"
               if info["active"] else "خاموش 🔴")
        return await reply(event, f"{HELP_FRIDGE}\n\nوضعیت این چت: {cur}")
    action, typ, off = _parse_game_args(toks, {"sell": "sell", "feed": "feed", "cat": "feed"})
    if off:
        await clear_sched(cid, FRIDGE_WORDS)
        set_fridge(cid, "sell", "off")
        await ensure()
        return await reply(event, "🧊 یخچال خودکار این چت خاموش شد 🔴")
    action = action or (info["action"] if info["active"] else "sell")
    typ = typ or "instant"
    await clear_sched(cid, FRIDGE_WORDS)
    set_fridge(cid, action, typ)
    await _enable("autofridge")
    if typ == "schedule":
        asyncio.create_task(_guarded(lambda e: fridge_kick(cid), event))
    await reply(event, f"🧊 یخچال خودکار ({'لحظه‌ای ⚡' if typ == 'instant' else 'زمان‌دار 📅'}) روشن شد 🟢\n"
                       f"▸ عملکرد: {FRIDGE_LABEL[action]}")


async def c_autobat(event, arg):
    cid = str(event.chat_id)
    toks = num(arg).lower().split()
    bats = M()["bat"]
    cfg = bats.get(cid, {"on": False, "delay": 1})
    if not toks:
        st = f"🟢 فعال (تأخیر {cfg.get('delay', 1)}s)" if cfg.get("on") else "🔴 خاموش"
        return await reply(event, f"{HELP_BAT}\n\nوضعیت این چت: {st}")
    cmd = toks[0]
    if cmd in ("on", "روشن"):
        cfg["on"] = True
        bats[cid] = cfg
        await _enable("autobat")
        return await reply(event, "🦇 شکار خودکار خفاش توی این چت روشن شد 🟢")
    if cmd in ("off", "خاموش"):
        cfg["on"] = False
        bats[cid] = cfg
        save_settings()
        return await reply(event, "🦇 شکار خودکار خفاش توی این چت خاموش شد 🔴")
    if cmd in ("delay", "تاخیر", "تأخیر"):
        if len(toks) > 1 and toks[1].isdigit():
            cfg["delay"] = max(0, min(115, int(toks[1])))
            bats[cid] = cfg
            save_settings()
            return await reply(event, f"⏱ تأخیر شکار خفاش: {cfg['delay']} ثانیه")
        return await reply(event, "عدد بین ۰ تا ۱۱۵ بده. مثال: `.autobat delay 2`")
    if cmd in ("list", "لیست"):
        rows = [f"`{k}` ➔ {v}" for k, v in sorted(BAT_EMOJI.items())]
        return await reply(event, "🦇 **کد ← ایموجی خفاش‌ها**\n\n" + "\n".join(rows))
    await reply(event, HELP_BAT)


async def c_show(event, arg):
    a = (arg or "").strip().lower()
    if not a:
        st = "روشن 🟢" if show_on() else "خاموش 🔴"
        return await event.edit(
            f"👁 **حالت نمایش دستورات**\n\nوضعیت: {st}\n\n"
            "خاموش کردنش جواب دستورهای بازی (میو، ماهیگیری، یخچال، نجات، خفاش، الیاس) رو نشون نمی‌ده "
            "و خود دستور رو پاک می‌کنه؛ برای اینکه ادمین‌ها متوجه ربات بودن نشن.\n\n"
            "▸ `.show on`\n▸ `.show off`")
    if a in ("on", "روشن"):
        M()["show"] = True
        save_settings()
        return await event.edit("👁 حالت نمایش روشن شد 🟢\nجواب دستورها نمایش داده می‌شه.")
    if a in ("off", "خاموش"):
        M()["show"] = False
        save_settings()
        await event.edit("👁 حالت نمایش خاموش شد 🔴\nدستورها بی‌صدا اجرا می‌شن و پیامشون پاک می‌شه.")
        await asyncio.sleep(2)
        try:
            await event.delete()
        except Exception:  # noqa
            pass
        return
    await event.edit("از `.show on` یا `.show off` استفاده کن")


async def c_sched(event, arg):
    parts = num(arg).split(maxsplit=2)
    help_ = ("⏰ **زمانبندی پیام روی سرور تلگرام**\n\n"
             "▸ `.sched تعداد فاصله‌به‌دقیقه متن`\n"
             "مثال: `.sched 10 5 میو` ← ۱۰ تا «میو» هر ۵ دقیقه (اکانت آنلاین نمی‌شه)\n"
             "حداکثر ۱۰۰ پیام؛ صف تلگرام برای هر چت ۱۰۰ تاست.")
    if len(parts) < 3:
        return await event.edit(help_)
    try:
        cnt, interval = int(parts[0]), int(parts[1])
    except ValueError:
        return await event.edit("⚠️ تعداد و فاصله باید عدد صحیح باشن\n\n" + help_)
    text = parts[2].strip()
    if cnt <= 0 or interval <= 0:
        return await event.edit("⚠️ تعداد و فاصله باید بزرگ‌تر از صفر باشن")
    if cnt > 100:
        return await event.edit("⚠️ حداکثر ۱۰۰ پیام مجازه")
    cid = event.chat_id
    existing = len(await sched_list(cid))
    if existing + cnt > 100:
        return await event.edit(f"⚠️ صف زمان‌دار این چت {existing} پیام داره؛ فقط {100 - existing} جا مونده")
    await event.edit("⏰ در حال ثبت پیام‌ها روی سرور تلگرام...")
    now, done = time.time(), 0
    _recent_sched[(cid, text)] = now + cnt * interval * 60 + 600
    for i in range(1, cnt + 1):
        try:
            await sched_send(cid, text, now + i * interval * 60)
            done += 1
        except FloodWaitError as e:
            log.warning("sched flood %ss", e.seconds)
            break
        except Exception as e:  # noqa
            log.warning("sched error at %s: %r", i, e)
            break
        await asyncio.sleep(0.35)
    await event.edit(f"✅ {done} پیام زمان‌بندی شد؛ هر {interval} دقیقه یک بار «{text}» ارسال می‌شه.")


async def c_alias(event, arg):
    toks = (arg or "").split(maxsplit=2)
    al = M()["aliases"]
    help_ = ("🔗 **میانبر دستورات (الیاس)**\n\n"
             "▸ `.alias add اسم دستور` ← افزودن\n"
             "▸ `.alias del اسم` ← حذف\n"
             "▸ `.alias list` ← لیست\n"
             "▸ `.alias clear` ← پاک‌کردن همه\n\n"
             "مثال: `.alias add am .automeow instant`\n"
             "آرگومان‌ها: `$1` `$2` یا `$*` · زنجیره: `&&` (حداکثر ۵ دستور)\n"
             "الیاس نمی‌تونه الیاس دیگه‌ای رو صدا بزنه. (فارسی: `.الیاس`)")
    if not toks:
        return await reply(event, help_)
    sub = toks[0].lower()
    if sub in ("add", "افزودن"):
        sp = (arg or "").split(maxsplit=2)
        if len(sp) < 3:
            return await reply(event, "مثال: `.alias add am .automeow instant`")
        ok, msg = add_alias(sp[1], sp[2])
        return await reply(event, msg)
    if sub in ("del", "حذف") and len(toks) > 1:
        name = _norm_alias(toks[1])
        if al.pop(name, None) is None:
            return await reply(event, f"⚠️ الیاس `{name}` پیدا نشد")
        save_settings()
        return await reply(event, f"✅ الیاس `{name}` حذف شد")
    if sub in ("list", "لیست"):
        if not al:
            return await reply(event, "⚠️ هیچ الیاسی ثبت نشده")
        rows = [f"{i}. `{k}` ➔ `{v.replace(chr(96), chr(39))}`" for i, (k, v) in enumerate(al.items(), 1)]
        return await reply(event, "🔗 **الیاس‌های فعال:**\n\n" + "\n".join(rows))
    if sub in ("clear", "reset", "پاک"):
        al.clear()
        save_settings()
        return await reply(event, "✅ همه‌ی الیاس‌ها پاک شدن")
    await reply(event, help_)


async def c_proxy(event, arg):
    a = (arg or "").strip()
    cur = CFG.get("proxy", "")
    help_ = ("🌐 **پروکسی**\n\n"
             f"وضعیت: {mask_proxy(cur) if cur else 'خاموش'}\n\n"
             "▸ `.proxy set socks5://user:pass@host:1080`\n"
             "▸ `.proxy set tg://proxy?server=...&port=443&secret=...` (MTProto)\n"
             "▸ `.proxy off`\n\n"
             "⚠️ بعد از تغییر باید سلف ریستارت بشه (Railway ← Restart). "
             "روی Railway معمولاً لازم نیست؛ تلگرام بلاک نیست.\n"
             "امن‌تر: آدرس رو توی متغیر `PROXY` بذار یا از پنل وب وارد کن.")
    if not a:
        return await event.edit(help_)
    head, _, rest = a.partition(" ")
    if head.lower() in ("off", "خاموش"):
        CFG["proxy"] = ""
        save_settings()
        return await event.edit("🌐 پروکسی خاموش شد (بعد از ریستارت اعمال می‌شه)")
    if head.lower() in ("set", "تنظیم") and rest.strip():
        link = rest.strip()
        if not parse_proxy_link(link):
            return await event.edit("❌ آدرس پروکسی معتبر نیست.\n\n" + help_)
        CFG["proxy"] = link
        save_settings()
        # پیام رو ادیت می‌کنیم تا آدرس/رمز توی چت نمونه
        return await event.edit(f"🌐 پروکسی ذخیره شد: {mask_proxy(link)}\nبرای اعمال، سلف رو ریستارت کن.")
    await event.edit(help_)


async def c_mstatus(event, arg):
    await event.edit(status_text(event.chat_id))
