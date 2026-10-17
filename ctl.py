"""کنترل از راه دور برای حالت هاب: هاب دستورها رو توی CTL_FILE می‌نویسه و وضعیت رو از STATUS_FILE می‌خونه.

هر کاربر یه پردازش جدا داره؛ این ماژول فقط وقتی فعاله که متغیر CTL_FILE ست شده باشه.
"""
import os
import json
import time
import asyncio

import core
import botpanel
import meow
from core import F, CFG, state, log

CTL = os.getenv("CTL_FILE", "")
STATUS = os.getenv("STATUS_FILE", "")
INSTANCE = bool(os.getenv("HUB_INSTANCE"))
START = time.time()
LOCKED = {"update"}  # توی حالت هاب فقط ادمین هاب با بات می‌تونه بروزرسانی کنه (کد بین همه مشترکه)


def prepare():
    """بعد از load_settings صدا زده می‌شه."""
    if INSTANCE:
        for k in LOCKED:
            F[k] = False


async def handle(op: dict):
    kind = op.get("op")
    if kind == "toggle":
        key = op.get("key")
        if key in LOCKED or key not in F:
            return
        await botpanel.toggle(key, bool(op.get("value")))
        await meow.ensure()
    elif kind == "run":
        if not (state.get("authorized") and core.client):
            log.info("ctl: run نادیده گرفته شد (وارد نشده)")
            return
        chat = op.get("chat")
        if isinstance(chat, str) and chat.lstrip("-").isdigit():
            chat = int(chat)
        text = str(op.get("text") or "")[:4000]
        if chat and text:
            await core.client.send_message(chat, text)
    else:
        log.info("ctl: عملیات ناشناخته %r", kind)


async def apply_ops():
    if not CTL or not os.path.exists(CTL):
        return
    work = CTL + ".work"
    try:
        os.replace(CTL, work)  # اتمیک: هاب بعدش فایل جدید می‌سازه و چیزی گم نمی‌شه
    except OSError:
        return
    try:
        with open(work, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            await handle(json.loads(line))
        except Exception as e:  # noqa
            log.warning("ctl op failed: %r", e)
    try:
        os.remove(work)
    except OSError:
        pass


def write_status():
    if not STATUS:
        return
    loops = {}
    for kind, cid in meow.TASKS:
        loops[kind] = loops.get(kind, 0) + 1
    data = {
        "ts": time.time(),
        "uptime": int(time.time() - START),
        "authorized": bool(state.get("authorized")),
        "me": state.get("me"),
        "restarts": CFG.get("restarts", 0),
        "loops": loops,
        "on": sorted(k for k, v in F.items() if v),
    }
    tmp = STATUS + ".tmp"
    try:
        os.makedirs(os.path.dirname(STATUS) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, STATUS)
    except OSError as e:
        log.warning("status write failed: %s", e)


PROFILE_DIR = os.path.dirname(STATUS) if STATUS else ""
_profile_t = 0.0


def _atomic_write(path, data: bytes):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


async def refresh_profile():
    """اسم/یوزرنیم/عکس اکانت سلف رو کنار status.json می‌نویسه (profile.json + avatar.jpg) تا مینی‌اپ هاب نشونش بده.
    برای کاربرهایی که قبل از این قابلیت وصل شده بودن (یا ادمینِ منتقل‌شده) هم خودکار پر می‌شه."""
    global _profile_t
    if not (PROFILE_DIR and state.get("authorized") and core.client):
        return
    _profile_t = time.time()
    me = await core.client.get_me()
    name = " ".join(x for x in (getattr(me, "first_name", None), getattr(me, "last_name", None)) if x)
    _atomic_write(os.path.join(PROFILE_DIR, "profile.json"), json.dumps(
        {"id": me.id, "name": name or getattr(me, "username", None) or "—", "username": getattr(me, "username", None)},
        ensure_ascii=False).encode("utf-8"))
    path = os.path.join(PROFILE_DIR, "avatar.jpg")
    try:
        raw = await core.client.download_profile_photo(me, file=bytes, download_big=False)
    except Exception as e:  # noqa
        log.info("profile photo failed: %r", e)
        raw = None
    if raw and len(raw) <= 120_000:
        _atomic_write(path, raw)
    elif not raw and os.path.exists(path):
        os.remove(path)


async def loop():
    n = 0
    while True:
        try:
            await apply_ops()
            if n % 5 == 0:
                write_status()
            if state.get("authorized") and time.time() - _profile_t > (600 if _profile_t else 0):
                await refresh_profile()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa
            log.warning("ctl loop: %r", e)
        n += 1
        await asyncio.sleep(2)
