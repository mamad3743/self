"""آمار، هشدار، گزارش روزانه و ساعت خاموشی بازی میویی (فقط به core وابسته‌ست)."""
import os
import json
import time
import datetime

import core
from core import F, CFG, TZ, log, save_settings, state

ALERT_FILE = os.getenv("ALERT_FILE", "")  # حالت هاب: هشدارها اینجا نوشته می‌شن و هاب با بات می‌فرسته
_last_alert = {}
_dirty = False

STAT_LABELS = (
    ("meow", "🐱 میو"), ("fish", "🎣 ماهیگیری"), ("fridge", "🧊 یخچال (پخت/فروش)"),
    ("cat", "😺 برداشت پیشی"), ("cat_pts", "💰 میو پوینت برداشت‌شده"), ("bat", "🦇 خفاش"),
    ("catch", "🐈 نجات"), ("upgrade", "⬆️ ارتقای مقام"), ("errors", "⚠️ خطا"),
)


def now():
    return datetime.datetime.now(TZ)


def today() -> str:
    return now().strftime("%Y-%m-%d")


# ───────────── آمار ─────────────
def stats_of(day=None, create=True) -> dict:
    S = CFG.setdefault("stats", {})
    return S.setdefault(day or today(), {}) if create else S.get(day or today(), {})


def bump(key, n=1):
    global _dirty
    d = stats_of()
    d[key] = d.get(key, 0) + int(n)
    _dirty = True
    S = CFG["stats"]
    if len(S) > 14:  # فقط ۱۴ روز آخر
        for k in sorted(S)[:-14]:
            S.pop(k, None)


def flush():
    global _dirty
    if _dirty:
        _dirty = False
        save_settings()


def report_text(day) -> str:
    d = stats_of(day, create=False)
    rows = [f"{label}: {d[k]:,}" for k, label in STAT_LABELS if d.get(k)]
    return "\n".join(rows) if rows else "—  (فعالیتی ثبت نشده)"


def full_report() -> str:
    y = (now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    return (f"📊 <b>گزارش بازی میویی</b>\n\n<b>امروز ({today()})</b>\n{report_text(today())}"
            f"\n\n<b>دیروز ({y})</b>\n{report_text(y)}")


# ───────────── هشدار ─────────────
async def notify(text):
    """هشدار برای صاحب سلف: توی حالت هاب ← فایل هشدار (هاب با بات می‌فرسته)، وگرنه Saved Messages."""
    if ALERT_FILE:
        try:
            os.makedirs(os.path.dirname(ALERT_FILE) or ".", exist_ok=True)
            with open(ALERT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "text": text}, ensure_ascii=False) + "\n")
        except OSError as e:
            log.warning("alert file write failed: %s", e)
        return
    if core.client and state.get("authorized"):
        try:
            await core.client.send_message("me", text, parse_mode="html")
        except Exception as e:  # noqa
            log.warning("alert send failed: %r", e)


async def alert(key, text, cooldown=1800):
    if not F.get("alerts"):
        return
    t = time.time()
    if t - _last_alert.get(key, 0) < cooldown:
        return
    _last_alert[key] = t
    await notify(text)


async def maybe_report():
    """هر روز بعد از نیمه‌شب گزارش روز قبل رو می‌فرسته (اولین بار از فردا)."""
    if not F.get("report"):
        return
    t = today()
    last = CFG.get("report_last", "")
    if last == t:
        return
    if last:
        y = (now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        if CFG.get("stats", {}).get(y):
            await notify(f"📊 <b>گزارش روزانه ({y})</b>\n\n{report_text(y)}")
    CFG["report_last"] = t
    save_settings()


# ───────────── ساعت خاموشی ─────────────
def quiet_cfg() -> dict:
    q = CFG.setdefault("quiet", {})
    q.setdefault("from", 2)
    q.setdefault("to", 8)
    return q


def quiet_remaining(at=None) -> int:
    """اگه الان توی بازه‌ی خاموشیم، ثانیه‌ی مونده تا پایانش؛ وگرنه ۰."""
    if not F.get("quiet"):
        return 0
    q = quiet_cfg()
    a, b = int(q["from"]) % 24, int(q["to"]) % 24
    if a == b:
        return 0
    at = at or now()
    h = at.hour + at.minute / 60 + at.second / 3600
    inside = (a <= h < b) if a < b else (h >= a or h < b)
    if not inside:
        return 0
    end = at.replace(hour=b, minute=0, second=0, microsecond=0)
    if end <= at:
        end += datetime.timedelta(days=1)
    return max(1, int((end - at).total_seconds()))


def is_quiet() -> bool:
    return quiet_remaining() > 0
