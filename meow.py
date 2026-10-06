"""قابلیت‌های MeowAce-Self برای سلف:
میو/ماهیگیری/یخچال خودکار (لحظه‌ای و زمان‌دار روی سرور تلگرام)، شکار خفاش، حالت نمایش،
زمانبندی پیام، میانبر دستورات (الیاس)، پروکسی و اطلاعات کامل کاربر/چت.

تنظیمات توی CFG["meow"] ذخیره می‌شن (همون settings.json روی Volume).
"""
import re
import math
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
    m.setdefault("autocat", {})  # {chat: {"type": "instant"}} برداشت خودکار میو پوینت پیشی
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


async def wait_buttons(cid, msg_id, timeout, need=True):
    """منتظر ادیت پیام بات (need=True دکمه، یا تابع شرط)؛ آخرش پیام فعلی رو می‌گیره."""
    fut = _fut()
    _edit_w[(cid, msg_id)] = (fut, need)
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
    hm = re.search(r"(\d+)\s*ساعت", t)
    mm = re.search(r"(\d+)\s*دقیقه", t)
    sm = re.search(r"(\d+)\s*ثانیه", t)
    h_, m_, s_ = (int(x.group(1)) if x else 0 for x in (hm, mm, sm))
    return h_ * 3600 + m_ * 60 + s_ if (h_ or m_ or s_) else None


# ───────────── زمان‌دار روی سرور تلگرام ─────────────
_recent_sched = {}  # (chat, text) -> expiry؛ پیام‌های زمان‌دار نباید با «حالت متن» ادیت بشن


def format_guard(chat_id, text="") -> bool:
    """True یعنی این پیام مال بازی/زمانبندیه و نباید فرمت (ادیت) بشه."""
    sc, m = str(chat_id), M()
    if any(sc in m[k] for k in ("automeow", "autofish", "autofridge", "bat", "autocat")) or sc in CFG.get("catch", {}):
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


# ───────────── میو خودکار ─────────────
_main_cd = {}  # (chat) -> آخرین کولداون اصلی میو


def meow_on(cid) -> bool:
    return str(cid) in M()["automeow"]


def set_meow(cid, on: bool):
    if on:
        M()["automeow"][str(cid)] = {"type": "instant"}
    else:
        M()["automeow"].pop(str(cid), None)
    save_settings()


def parse_meow_cd(txt):
    t = num(txt)
    if not t or any(k in t for k in ("ماهی", "ماهیا", "خوابن", "قلاب", "طعمه", "یخچال")):
        return None
    return parse_clock_or_text(t)


async def meow_once(cid) -> int:
    """یه میو می‌فرسته؛ ثانیه‌ی دقیق نوبت بعدی رو از جواب بات برمی‌گردونه."""
    sent = await send_safe(cid, random.choice(MEOW_WORDS))
    rep = await wait_reply(cid, sent.id, 28)
    if not rep:
        return 60
    txt = rep.raw_text or ""
    cd = parse_meow_cd(txt)
    if cd is None:
        log.info("automeow: زمان انتظار توی جواب بات پیدا نشد: %r", txt[:200])
        return 255
    if "هنوز میوت نمیاد" not in txt:
        _main_cd[cid] = cd
    return cd


async def meow_loop(cid):
    while True:
        if not (F["automeow"] and meow_on(cid)):
            return
        try:
            async with chat_lock(cid):
                cd = await meow_once(cid)
        except FloodWaitError as e:
            cd = e.seconds + 5
        except Exception as e:  # noqa
            log.warning("automeow %s: %r", cid, e)
            cd = 60
        await asyncio.sleep(cd + 1)  # دقیقاً همون زمانی که بات گفت (+۱ ثانیه برای اینکه زودتر نرسیم)


# ───────────── ماهیگیری خودکار ─────────────
FISH_KW = {"feed": "پیشی", "sell": "فروش", "fridge": "یخچال"}
FISH_LABEL = {"feed": "غذادادن به پیشی 🐱", "sell": "فروش مستقیم ماهی 💰", "fridge": "ذخیره در یخچال 🧊"}
_fish_streak = {}  # چند بار پشت‌سرهم بدون دیدن کولداون عمل کردیم (ترمز ایمنی)


def fish_info(cid) -> dict:
    v = M()["autofish"].get(str(cid))
    return {"active": bool(v), "action": (v or {}).get("action", "feed")}


def set_fish(cid, action, on: bool):
    if on:
        M()["autofish"][str(cid)] = {"action": action, "type": "instant"}
    else:
        M()["autofish"].pop(str(cid), None)
    save_settings()


FISH_CD_WORDS = ("صبر کنی", "خوابن", "کولداون", "کافیه")


def parse_fish_cd(txt, has_action_btn=False):
    """زمان انتظار ماهیگیری از متن بات (هر قالبی: «۴۴ دقیقه»، «۱ ساعت و ۱۰ دقیقه»، «۴۴:۰۰»)."""
    t = num(txt)
    if has_action_btn:
        return None
    cd = parse_clock_or_text(t)
    if cd:
        return min(cd, 6 * 3600)
    if any(k in t for k in FISH_CD_WORDS):
        return 300
    return None


def _has_fish_btn(msg, action) -> bool:
    return bool(msg and msg.buttons and find_btn(msg, FISH_KW.get(action, "پیشی")))


async def fish_act(cid, init, action) -> int:
    """بعد از جواب بات به «ماهی»: یا زمان انتظار رو می‌خونه یا دکمه‌ی مناسب رو می‌زنه؛ ثانیه‌ی نوبت بعدی رو برمی‌گردونه.
    بعد از زدن دکمه، چند ثانیه بعد دوباره «ماهی» می‌فرستیم تا بات زمان انتظار تصادفی بعدی رو بگه و دقیق همون‌قدر صبر کنیم."""
    cd = parse_fish_cd(init.raw_text or "", _has_fish_btn(init, action))
    if cd:
        _fish_streak[cid] = 0
        return cd + 1
    target = init
    if not _has_fish_btn(init, action):
        # بات ممکنه پیام رو بعداً ادیت کنه؛ منتظر دکمه یا متن زمان انتظار می‌مونیم
        target = await wait_buttons(
            cid, init.id, 24,
            need=lambda m: _has_fish_btn(m, action) or parse_fish_cd(m.raw_text or "") is not None)
    if not target:
        return 120
    if not _has_fish_btn(target, action):
        cd = parse_fish_cd(target.raw_text or "")
        if cd:
            _fish_streak[cid] = 0
            return cd + 1
        log.info("autofish: جواب بات قابل فهم نبود (نه دکمه نه زمان): %r", (target.raw_text or "")[:200])
        return 120
    await asyncio.sleep(random.uniform(0.8, 1.6))
    btn = find_btn(target, FISH_KW.get(action, "پیشی"))
    if action == "fridge":
        f_msg = await click_wait(btn, cid, target.id, 12, need_buttons=False, fallback=False)
        if f_msg and any(k in (f_msg.raw_text or "") for k in ("جا نداره", "پر", "قبل", "موجود", "یخچال")):
            s_btn = find_btn(f_msg, "فروش")  # یخچال پر بود ← جایگزین: فروش
            if s_btn:
                await asyncio.sleep(1.0)
                await s_btn.click()
    else:
        await btn.click()
    _fish_streak[cid] = _fish_streak.get(cid, 0) + 1
    return 8 if _fish_streak[cid] < 3 else 120  # اگه بات هیچ‌وقت کولداون نگفت، اسپم نکنیم


async def fish_loop(cid):
    while True:
        info = fish_info(cid)
        if not (F["autofish"] and info["active"]):
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


# ───────────── یخچال خودکار ─────────────
FRIDGE_LABEL = {"sell": "پخت ماهی خام و فروش پخته‌ها 💰", "feed": "پخت ماهی خام و غذادادن به پیشی 🐱"}


def fridge_info(cid) -> dict:
    v = M()["autofridge"].get(str(cid))
    return {"active": bool(v), "action": (v or {}).get("action", "sell")}


def set_fridge(cid, action, on: bool):
    if on:
        M()["autofridge"][str(cid)] = {"action": action, "type": "instant"}
    else:
        M()["autofridge"].pop(str(cid), None)
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
                return cook_sec + 3
            return 120
        return 1800
    return 1800


async def fridge_loop(cid):
    while True:
        info = fridge_info(cid)
        if not (F["autofridge"] and info["active"]):
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
        await asyncio.sleep(max(sleep, 10))


# ───────────── پیشی: برداشت خودکار میو پوینت ─────────────
CAT_WORD = "پیشی"
_cat_streak = {}


def cat_on(cid) -> bool:
    return str(cid) in M()["autocat"]


def set_cat(cid, on: bool):
    if on:
        M()["autocat"][str(cid)] = {"type": "instant"}
    else:
        M()["autocat"].pop(str(cid), None)
    save_settings()


def _to_float(txt):
    t = re.sub(r"[,٬،\s]", "", num(txt)).strip(".")
    try:
        return float(t)
    except ValueError:
        return None


def parse_cat(txt):
    """از پیام «پیشی»: (میو پوینت تولید‌شده، ظرفیت، تولید در ثانیه) ← یا None."""
    t = num(txt or "")
    out = []
    for pat in (r"تولید\s*شده[^\d\n]{0,8}([\d,٬،.]+)", r"ظرفیت[^\d\n]{0,8}([\d,٬،.]+)",
                r"در\s*ثانیه[^\d\n]{0,8}([\d,٬،.]+)"):
        m = re.search(pat, t)
        v = _to_float(m.group(1)) if m else None
        if v is None:
            return None
        out.append(v)
    return tuple(out)


async def cat_act(cid, init) -> int:
    """زمان پر شدن ظرفیت رو دقیق حساب می‌کنه؛ پر بود ← «برداشت میو پوینت ها» رو می‌زنه.
    ثانیه‌ی نوبت بعدی رو برمی‌گردونه (بعد از برداشت چند ثانیه بعد دوباره می‌خونه تا زمان دقیق بعدی رو بفهمه)."""
    target = init
    if not parse_cat(init.raw_text):
        target = await wait_buttons(cid, init.id, 20, need=lambda m: parse_cat(m.raw_text or "") is not None)
    data = parse_cat(target.raw_text if target else "")
    if not data:
        log.info("autocat: اعداد توی جواب بات پیدا نشد: %r", ((target.raw_text if target else "") or "")[:300])
        return 900
    prod, cap, rate = data
    if prod >= cap:
        btn = find_btn(target, "برداشت")
        if not btn:
            log.info("autocat: ظرفیت پره ولی دکمه‌ی برداشت پیدا نشد")
            return 120
        await asyncio.sleep(random.uniform(0.8, 1.6))
        await btn.click()
        _cat_streak[cid] = _cat_streak.get(cid, 0) + 1
        return 6 if _cat_streak[cid] < 3 else 300  # اگه برداشت جواب نداد، اسپم نکنیم
    _cat_streak[cid] = 0
    if rate <= 0:
        return 900
    return int(min(math.ceil((cap - prod) / rate), 86400)) + 2  # رو به بالا گرد می‌شه تا موقع بیدارشدن حتماً پر باشه


async def cat_loop(cid):
    while True:
        if not (F["autocat"] and cat_on(cid)):
            return
        try:
            async with chat_lock(cid):
                sent = await send_safe(cid, CAT_WORD)
                init = await wait_reply(cid, sent.id, 20)
                sleep = await cat_act(cid, init) if init else 60
        except FloodWaitError as e:
            sleep = e.seconds + 5
        except Exception as e:  # noqa
            log.warning("autocat %s: %r", cid, e)
            sleep = 60
        await asyncio.sleep(sleep)


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


# ───────────── مدیریت حلقه‌ها ─────────────
LOOPS = {"meow": meow_loop, "fish": fish_loop, "fridge": fridge_loop, "cat": cat_loop}
FIELDS = {"meow": ("automeow", "automeow"), "fish": ("autofish", "autofish"), "fridge": ("autofridge", "autofridge"),
          "cat": ("autocat", "autocat")}
TASKS = {}
_migrated = False


def _desired():
    out = set()
    if not state.get("authorized") or core.client is None:
        return out
    for kind, (feat, field) in FIELDS.items():
        if F.get(feat):
            for cid in M()[field]:
                out.add((kind, int(cid)))
    return out


async def _migrate():
    """نسخه‌ی قبلی حالت «زمان‌دار» داشت؛ حالا همه خودکارِ لحظه‌ای‌ان. پیام‌های زمان‌دار قدیمی از سرور تلگرام پاک می‌شن."""
    global _migrated
    if _migrated:
        return
    _migrated, changed = True, False
    for _kind, (field, words) in {"m": ("automeow", MEOW_WORDS), "f": ("autofish", FISH_WORDS),
                                  "r": ("autofridge", FRIDGE_WORDS)}.items():
        for cid, v in list(M()[field].items()):
            if v.get("type") == "schedule":
                v["type"], changed = "instant", True
                await clear_sched(int(cid), words)
    if changed:
        save_settings()


async def ensure():
    """حلقه‌ها رو با تنظیمات فعلی هماهنگ می‌کنه (شروع/توقف)."""
    want = _desired()
    for key in list(TASKS):
        if key not in want or TASKS[key].done():
            TASKS.pop(key).cancel()
    for key in want - set(TASKS):
        TASKS[key] = asyncio.create_task(LOOPS[key[0]](key[1]))


async def supervisor():
    while True:
        try:
            if state.get("authorized") and core.client is not None:
                await _migrate()
            await ensure()
        except Exception as e:  # noqa
            log.exception("meow supervisor: %s", e)
        await asyncio.sleep(30)


# ───────────── رویدادها ─────────────
async def on_incoming(event):
    """جواب‌های بات به پیام‌های من ← آزاد کردن منتظرها."""
    if not state.get("authorized"):
        return
    rid = event.reply_to_msg_id
    if not rid:
        return
    fut = _reply_w.get((event.chat_id, rid))
    if fut and not fut.done():
        fut.set_result(event.message)


async def on_edit(event):
    entry = _edit_w.get((event.chat_id, event.message.id))
    if not entry:
        return
    fut, need = entry
    if fut.done():
        return
    okk = need(event.message) if callable(need) else (not need or event.message.buttons)
    if okk:
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

    def onoff(b, extra=""):
        return ("🟢 روشن" + (f" ({extra})" if extra else "")) if b else "🔴 خاموش"

    fi, ri = fish_info(cid), fridge_info(cid)
    c = CFG.get("catch", {}).get(sc)
    catch = onoff(bool(c), f"کلمه: {c.get('word', 'نجات')} · تأخیر: {c.get('delay', 1.0):g}s · "
                           f"تعداد: {c.get('times', 2)}" if c else "")
    b = m["bat"].get(sc)
    bat = onoff(bool(b and b.get("on")), f"تأخیر: {b.get('delay', 1)}s" if b else "")
    master = [k for k in ("automeow", "autofish", "autofridge", "autocat", "autocatch", "autobat") if not F.get(k)]
    warn = ("\n\n⚠️ کلید کلی این قابلیت‌ها توی پنل خاموشه: " + "، ".join(master)) if master else ""
    return (
        "🐾 **وضعیت بازی میویی توی این چت**\n\n"
        f"📍 چت: `{cid}`\n\n"
        f"🐱 میویی: {onoff(meow_on(cid))}\n"
        f"🎣 ماهیگیری: {onoff(fi['active'], FISH_LABEL[fi['action']] if fi['active'] else '')}\n"
        f"🧊 یخچال: {onoff(ri['active'], FRIDGE_LABEL[ri['action']] if ri['active'] else '')}\n"
        f"😺 پیشی (برداشت میو پوینت): {onoff(cat_on(cid))}\n"
        f"🐈 نجات: {catch}\n"
        f"🦇 خفاش: {bat}\n"
        f"👁 حالت نمایش: {onoff(show_on())}"
        + warn
    )


# ───────────── دستورها (هر بازی یه دستور؛ بدون آرگومان = روشن/خاموش) ─────────────
async def _enable(feat):
    F[feat] = True
    save_settings()
    await ensure()


ON_WORDS = {"on", "روشن", "start", "شروع", "instant", "live", "فوری", "schedule", "sched", "زمان‌دار", "زماندار"}
OFF_WORDS = {"off", "خاموش", "stop", "توقف"}

HELP_MEOW = ("🐱 **میویی** ← `.میویی` روشن/خاموش می‌کنه. زمان انتظار رو از جواب بات می‌خونه و دقیق همون موقع "
             "خودش می‌فرسته.\n(`.میویی روشن` · `.میویی خاموش`)")
HELP_FISH = ("🎣 **ماهیگیری** ← `.ماهیگیری` روشن/خاموش می‌کنه.\n"
             "انتخاب عملکرد: `.ماهیگیری پیشی` (غذا به پیشی، پیش‌فرض) · `.ماهیگیری فروش` · `.ماهیگیری یخچال`")
HELP_FRIDGE = ("🧊 **یخچال** ← `.یخچال` روشن/خاموش می‌کنه.\n"
               "انتخاب عملکرد: `.یخچال فروش` (پیش‌فرض) · `.یخچال پیشی`")
HELP_BAT = ("🦇 **خفاش** ← `.خفاش` روشن/خاموش می‌کنه.\n"
            "`.خفاش تاخیر 2` (۰ تا ۱۱۵ ثانیه) · `.خفاش لیست` (جدول کد ← ایموجی)\n"
            "✋ دستی: روی پیام خفاش ریپلای کن و بنویس `batt`")


def _want(toks, active):
    """True=روشن، False=خاموش، None=ورودی نامفهوم. بدون آرگومان ← برعکس حالت فعلی."""
    toks = [t for t in toks if not t.isdigit()]
    if not toks:
        return not active
    if any(t in OFF_WORDS for t in toks):
        return False
    if any(t in ON_WORDS for t in toks):
        return True
    return None


async def c_automeow(event, arg):
    cid = event.chat_id
    w = _want(num(arg).lower().split(), meow_on(cid))
    if w is None:
        return await reply(event, HELP_MEOW)
    if w:
        await clear_sched(cid, MEOW_WORDS)  # باقی‌مونده‌ی نسخه‌ی قدیمی
        set_meow(cid, True)
        await _enable("automeow")
        return await reply(event, "🐱 میویی روشن شد 🟢\nزمان انتظار رو از جواب بات می‌خونم و دقیق همون موقع می‌فرستم.")
    set_meow(cid, False)
    await ensure()
    await reply(event, "🐱 میویی این چت خاموش شد 🔴")


async def c_autofish(event, arg):
    cid = event.chat_id
    toks = num(arg).lower().split()
    acts = {"feed": "feed", "cat": "feed", "پیشی": "feed", "غذا": "feed", "sell": "sell", "فروش": "sell",
            "fridge": "fridge", "یخچال": "fridge"}
    action = next((acts[t] for t in toks if t in acts), None)
    info = fish_info(cid)
    rest = [t for t in toks if t not in acts]
    w = True if (action and not any(t in OFF_WORDS for t in rest)) else _want(rest, info["active"])
    if w is None:
        return await reply(event, HELP_FISH)
    if w:
        action = action or (info["action"] if info["active"] else "feed")
        set_fish(cid, action, True)
        await _enable("autofish")
        return await reply(event, f"🎣 ماهیگیری روشن شد 🟢\n▸ عملکرد: {FISH_LABEL[action]}")
    set_fish(cid, "feed", False)
    await ensure()
    await reply(event, "🎣 ماهیگیری این چت خاموش شد 🔴")


async def c_autofridge(event, arg):
    cid = event.chat_id
    toks = num(arg).lower().split()
    acts = {"sell": "sell", "فروش": "sell", "feed": "feed", "cat": "feed", "پیشی": "feed", "غذا": "feed"}
    action = next((acts[t] for t in toks if t in acts), None)
    info = fridge_info(cid)
    rest = [t for t in toks if t not in acts]
    w = True if (action and not any(t in OFF_WORDS for t in rest)) else _want(rest, info["active"])
    if w is None:
        return await reply(event, HELP_FRIDGE)
    if w:
        action = action or (info["action"] if info["active"] else "sell")
        set_fridge(cid, action, True)
        await _enable("autofridge")
        return await reply(event, f"🧊 یخچال روشن شد 🟢\n▸ عملکرد: {FRIDGE_LABEL[action]}")
    set_fridge(cid, "sell", False)
    await ensure()
    await reply(event, "🧊 یخچال این چت خاموش شد 🔴")


HELP_CAT = ("😺 **پیشی** ← `.پیشی` روشن/خاموش می‌کنه.\n"
            "از پیام «پیشی» ظرفیت و سرعت تولید رو می‌خونه، زمان پر شدن رو دقیق حساب می‌کنه و "
            "همون موقع «برداشت میو پوینت ها» رو می‌زنه.")


async def c_autocat(event, arg):
    cid = event.chat_id
    w = _want(num(arg).lower().split(), cat_on(cid))
    if w is None:
        return await reply(event, HELP_CAT)
    if w:
        set_cat(cid, True)
        await _enable("autocat")
        return await reply(event, "😺 برداشت خودکار میو پوینت روشن شد 🟢\nوقتی ظرفیت پر شد خودم برمی‌دارم.")
    set_cat(cid, False)
    await ensure()
    await reply(event, "😺 برداشت خودکار میو پوینت این چت خاموش شد 🔴")


async def c_autobat(event, arg):
    cid = str(event.chat_id)
    toks = num(arg).lower().split()
    bats = M()["bat"]
    cfg = bats.get(cid, {"on": False, "delay": 1})
    if toks and toks[0] in ("delay", "تاخیر", "تأخیر"):
        if len(toks) > 1 and toks[1].isdigit():
            cfg["delay"] = max(0, min(115, int(toks[1])))
            bats[cid] = cfg
            save_settings()
            return await reply(event, f"⏱ تأخیر شکار خفاش: {cfg['delay']} ثانیه")
        return await reply(event, "عدد بین ۰ تا ۱۱۵ بده. مثال: `.خفاش تاخیر 2`")
    if toks and toks[0] in ("list", "لیست"):
        rows = [f"`{k}` ➔ {v}" for k, v in sorted(BAT_EMOJI.items())]
        return await reply(event, "🦇 **کد ← ایموجی خفاش‌ها**\n\n" + "\n".join(rows))
    w = _want(toks, bool(cfg.get("on")))
    if w is None:
        return await reply(event, HELP_BAT)
    cfg["on"] = w
    bats[cid] = cfg
    if w:
        await _enable("autobat")
        return await reply(event, f"🦇 شکار خودکار خفاش روشن شد 🟢 (تأخیر {cfg.get('delay', 1)} ثانیه)")
    save_settings()
    await reply(event, "🦇 شکار خودکار خفاش این چت خاموش شد 🔴")


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
