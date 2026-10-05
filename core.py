"""تنظیمات مشترک، لیست قابلیت‌ها، ذخیره‌سازی و ابزارهای تاریخ/ساعت."""
import os
import re
import json
import time
import hmac
import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("self")

# ───────────── تنظیمات محیطی ─────────────
API_FILE = os.getenv("API_FILE", "/data/api.json")
API = {"id": int(os.getenv("API_ID") or 0), "hash": os.getenv("API_HASH", "")}
PANEL_PASSWORD = os.environ["PANEL_PASSWORD"]  # رمز ورود به پنل وب
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tehran"))
SESSION_FILE = os.getenv("SESSION_FILE", "/data/session.txt")
SETTINGS_FILE = os.getenv("SETTINGS_FILE", "/data/settings.json")
PORT = int(os.getenv("PORT", "8080"))
PANEL_TTL = int(os.getenv("PANEL_TTL", "300"))  # حذف خودکار پنل داخل چت (ثانیه؛ 0 = بدون حذف)
TOKEN = hmac.new(PANEL_PASSWORD.encode(), b"panel", hashlib.sha256).hexdigest()

# ───────────── لیست قابلیت‌ها ─────────────
# key, emoji, name, toggle(روشن/خاموش‌شدنی؟), توضیح, نمونه دستورها
_RAW = [
    ("canned", "📋", "متن‌های آماده", False,
     "متن‌هایی که زیاد می‌فرستی رو ذخیره کن و با یه دستور بفرست.",
     [".متن ذخیره سلام | سلام، خوبی؟", ".متن سلام", ".متن لیست", ".متن حذف سلام"]),
    ("clock", "🕐", "ساعت", True,
     "ساعت زنده توی فامیلی یا بیو پروفایل (به وقت TIMEZONE).",
     [".ساعت on", ".ساعت off", ".ساعت bio", ".ساعت name", ".ساعت font 2", ".ساعت emoji ⏰"]),
    ("guard", "🛡", "نگهبان چت", True,
     "توی گروه‌هایی که ادمینی، پیام‌های حاوی لینک/یوزرنیم از غیرادمین‌ها پاک می‌شه. "
     "باید توی هر گروه با دستور فعال بشه.",
     [".نگهبان on", ".نگهبان off"]),
    ("locks", "🔒", "قفل‌ها", True,
     "قفل کردن نوع پیام توی گروه (لینک، فوروارد، عکس، ویدیو، استیکر، ویس، گیف، فایل، منشن). "
     "پیام ممنوعه از غیرادمین‌ها پاک می‌شه.",
     [".قفل لینک", ".بازکردن لینک", ".قفل لیست", ".بازکردن همه"]),
    ("action", "🎬", "اکشن", False,
     "توی چت فعلی «در حال تایپ/ضبط ویس/...» نشون بده (پیش‌فرض ۶۰ ثانیه).",
     [".اکشن تایپ 60", ".اکشن ویس", ".اکشن ویدیو", ".اکشن بازی", ".اکشن off"]),
    ("format", "🔤", "حالت متن", True,
     "همه‌ی پیام‌هات خودکار بولد/ایتالیک/مونو/اسپویلر/... می‌شن.",
     [".فرمت bold", ".فرمت mono", ".فرمت off"]),
    ("filter", "🚫", "فیلتر کلمات", True,
     "کلمات ممنوعه‌ی هر گروه؛ پیام‌های حاوی اون‌ها از غیرادمین‌ها پاک می‌شه.",
     [".فیلتر اضافه کلمه", ".فیلتر حذف کلمه", ".فیلتر لیست"]),
    ("ping", "📶", "پینگ", False,
     "سرعت پاسخ‌گویی سلف رو نشون می‌ده.", [".پینگ"]),
    ("logo", "🖼", "لوگو", False,
     "ساخت عکس لوگو با متن دلخواه و پس‌زمینه‌ی رنگی (استایل ۱ تا ۵).",
     [".لوگو Erfan", ".لوگو سازینو 3"]),
    ("forcejoin", "🔐", "عضویت اجباری", True,
     "توی گروه فقط اعضای یه کانال می‌تونن پیام بدن (باید ادمین گروه باشی).",
     [".عضویت @channel", ".عضویت off"]),
    ("friends", "🤝", "دوستان", True,
     "به پی‌وی دوستات خودکار ❤️ ریکت می‌زنه. افراد «نادیده» هم از قابلیت‌های خودکار "
     "(آفلاین، منشی، جواب‌ها، سین) کنار گذاشته می‌شن.",
     [".دوست (روی ریپلای)", ".دوست حذف", ".دوست لیست", ".نادیده (روی ریپلای)", ".نادیده حذف"]),
    ("secretary", "🧑‍💼", "منشی", True,
     "به پی‌وی‌ها (هر نفر هر ۶ ساعت یه بار) با متن منشی جواب می‌ده. "
     "{name} {date} {time} قابل استفاده‌ست.",
     [".منشی سلام {name}، منشی هستم؛ پیامت ثبت شد", ".منشی off"]),
    ("autoreply", "💬", "پاسخ خودکار", True,
     "به کلمات خاص توی پی‌وی جواب آماده می‌ده (هر نفر هر کلمه ۳۰ ثانیه یه بار).",
     [".جواب سلام | علیک سلام", ".جواب لیست", ".جواب حذف سلام"]),
    ("react", "❤️", "ریکت", True,
     "روی همه‌ی پیام‌های دریافتی همین چت ریکشن می‌زنه.",
     [".ریکت ❤️", ".ریکت off"]),
    ("antidel", "🗑", "ضد حذف", True,
     "متن پیام‌های حذف/ویرایش‌شده‌ی پی‌وی رو توی Saved Messages برات می‌ذاره (فقط متن).",
     [".ضدحذف on", ".ضدحذف off"]),
    ("delete", "🧹", "حذف", False,
     "پیام‌های خودت توی همین چت رو پاک می‌کنه.", [".حذف", ".حذف 10"]),
    ("savephoto", "📷", "ذخیره عکس", False,
     "روی یه پیام (عکس/فایل) ریپلای کن تا توی Saved Messages ذخیره شه. "
     "پیام‌های تایمردار و چت‌های محافظت‌شده ذخیره نمی‌شن.",
     [".ذخیره (روی ریپلای)"]),
    ("download", "⬇️", "دانلودر", False,
     "فایل رو از لینک مستقیم دانلود و توی چت می‌فرسته (تا ۱۰۰ مگابایت).",
     [".دانلود https://example.com/file.pdf"]),
    ("mute", "🔇", "سکوت", True,
     "توی گروه (باید ادمین باشی) یه نفر رو ساکت می‌کنه.",
     [".سکوت (روی ریپلای)", ".لغوسکوت (روی ریپلای)"]),
    ("info", "ℹ️", "اطلاعات", False,
     "اطلاعات کامل کاربر/کانال/گروه: آیدی، نام، یوزرنیم، نوع، دیتاسنتر، پریمیوم، بیو، گروه‌های مشترک، "
     "منبع پیام فوروارد‌شده و آیدی چت/پیام. با ریپلای، یوزرنیم، آیدی یا لینک t.me کار می‌کنه.",
     [".اطلاعات (روی ریپلای)", ".اطلاعات @username", ".اطلاعات 123456789"]),
    ("block", "⛔", "بلاک", False,
     "کاربر رو بلاک/آنبلاک می‌کنه (روی ریپلای یا توی پی‌وی همون نفر).",
     [".بلاک", ".آنبلاک"]),
    ("calc", "➗", "ماشین‌حساب", False,
     "ماشین‌حساب امن (+ - * / ** % //).", [".حساب 2*(3+4)", ".حساب 2**10"]),
    ("autoseen", "👀", "سین خودکار", True,
     "پیام‌های پی‌وی خودکار خونده (seen) می‌شن.", [".سین on", ".سین off"]),
    ("ai", "🤖", "هوش مصنوعی", False,
     "سوال از Claude. نیاز به متغیر ANTHROPIC_API_KEY توی Railway داره.",
     [".هوش فرق HTTP و HTTPS چیه؟", ".هوش (روی ریپلای)"]),
    ("translate", "🌐", "ترجمه", False,
     "ترجمه‌ی متن یا پیام ریپلای‌شده. بدون زبان: فارسی↔انگلیسی خودکار.",
     [".ترجمه hello world", ".ترجمه de سلام دنیا", ".ترجمه (روی ریپلای)"]),
    ("animation", "✨", "انیمیشن", False,
     "انیمیشن‌های متنی: ماه، قلب، لودینگ، ساعت، موج.",
     [".انیمیشن ماه", ".انیمیشن قلب", ".انیمیشن لودینگ"]),
    ("cheat", "🎲", "تقلب", False,
     "تاس 🎲 می‌ندازه و تا رسیدن به عدد دلخواه ادامه می‌ده (حداکثر ۱۲ بار).",
     [".تقلب 6"]),
    ("tts", "🔊", "تبدیل متن به صدا", False,
     "متن رو به ویس تبدیل می‌کنه. Google TTS فارسی نداره؛ زبان‌ها: en ar tr de fr es ru hi ur ...",
     [".صدا hello my friend", ".صدا tr merhaba"]),
    ("videosearch", "📹", "سرچ ویدیو", False,
     "لینک جستجوی ویدیو توی یوتیوب و آپارات می‌سازه.", [".ویدیو آموزش پایتون"]),
    ("news", "📰", "اخبار", False,
     "آخرین تیترهای خبری (RSS). با متغیر NEWS_RSS می‌تونی منبعش رو عوض کنی.", [".اخبار"]),
    ("music", "🎵", "سرچ آهنگ", False,
     "جستجوی آهنگ (iTunes) و لینک پیش‌نمایش ۳۰ ثانیه‌ای.", [".آهنگ Shape of You"]),
    ("mention", "🔔", "ذخیره منشن‌ها", True,
     "وقتی توی گروه‌ها منشن می‌شی، پیام توی Saved Messages ذخیره می‌شه.",
     [".منشن on", ".منشن off"]),
    ("afk", "🌙", "آفلاین", True,
     "به پی‌وی‌ها (هر نفر هر ۱۵ دقیقه یه بار) پیام آفلاین می‌ده. با «ساعت سکوت» "
     "می‌تونی بازه‌ای (مثلاً شب‌ها) تعریف کنی که خودکار آفلاین باشی.",
     [".آفلاین رفتم بیرون", ".آفلاین off", ".آفلاین ساعت 23:00-07:00 (زمان‌بندی خودکار)", ".آفلاین ساعت off"]),
    ("online", "🟢", "همیشه آنلاین", True,
     "هر ۲۵ ثانیه وضعیت رو آنلاین نگه می‌داره.", [".آنلاین on", ".آنلاین off"]),
    ("firstcomment", "🥇", "کامنت اول", True,
     "برای کانال‌هایی که انتخاب کردی، زیر هر پست جدید خودکار کامنت می‌ذاره "
     "(هر کانال حداقل ۲۰ ثانیه فاصله).",
     [".کامنت add @channel", ".کامنت متن اول! 🥇", ".کامنت لیست", ".کامنت حذف @channel"]),
    ("currency", "💱", "قیمت ارز", False,
     "نرخ بازار آزاد از tgju.org (به تومان): دلار، یورو، پوند، درهم، لیر، طلا ۱۸، مثقال و انواع سکه. "
     "می‌تونی مقدار هم بدی. بیت‌کوین و اتریوم هم هست.",
     [".ارز", ".ارز دلار", ".ارز 100 یورو", ".ارز سکه"]),
    ("date", "📅", "تاریخ شمسی", True,
     "تاریخ شمسی امروز کنار بیو پروفایل. دستور .تاریخ هم تاریخ کامل رو می‌گه.",
     [".تاریخ"]),
    ("options", "🎛", "گزینه‌های پنل", False,
     "تنظیمات خود پنل: زمان حذف خودکار، چت‌های مجاز برای نمایش پنل، و رنگ‌بندی دکمه‌ها.",
     [".پنل تنظیمات", ".پنل زمان 120", ".پنل اینجا", ".پنل محدود on", ".پنل رنگ mono"]),
    ("backup", "💾", "پشتیبان", False,
     "از تنظیمات (بدون توکن بات و سشن) فایل پشتیبان توی Saved Messages می‌ذاره؛ "
     "با ریپلای روی فایل برمی‌گردونیش (مثلاً اگه Volume پاک شد).",
     [".پشتیبان", ".بازیابی (روی فایل ریپلای)"]),
    ("autotask", "⏲", "کارهای زمان‌بندی‌شده", True,
     "یه دستور یا کلیک روی دکمه‌ی یه بات رو هر چند دقیقه یه بار خودکار انجام می‌ده "
     "(مثلاً برای بازی‌های بات‌ها). حداقل فاصله ۱ دقیقه، حداکثر ۱۰ کار. "
     "کار برای چتی ثبت می‌شه که دستور رو توش می‌زنی. حالت «هوشمند»: اگه بات توی جوابش "
     "زمان انتظار (مثلاً «۲ دقیقه و ۳۰ ثانیه») بگه، نوبت بعدی دقیقاً بعد از همون زمان اجرا می‌شه.",
     [".خودکار افزودن 5m میو", ".خودکار هوشمند 5m میو", ".خودکار کلیک 10m ماهیگیری", ".خودکار لیست",
      ".خودکار توقف 1", ".خودکار شروع 1", ".خودکار حذف 1", ".خودکار پاک", ".میویی"]),
    ("autocatch", "🐈", "نجات خودکار", True,
     "وقتی بات توی یه چت پیامی با دکمه‌ای شامل کلمه‌ی «نجات» (یا هر کلمه‌ی دلخواه) می‌فرسته، "
     "خودکار روش کلیک می‌کنه؛ مثلاً نجات گربه‌ی خیابونی توی بازی میویی. تأخیر و تعداد کلیک روی "
     "ادیت پیام (۱ تا ۳) قابل تنظیمه.",
     [".نجات on", ".نجات کلمه نجات", ".نجات تاخیر 1.5", ".نجات تعداد 2", ".نجات off", "/autocatch on"]),
    ("automeow", "🐱", "میو خودکار", True,
     "کلمه‌ی میو رو خودکار می‌فرسته و کولداون رو از جواب بات می‌خونه. حالت لحظه‌ای، یا حالت زمان‌دار "
     "که پیام‌ها روی سرور تلگرام زمان‌بندی می‌شن و اکانتت آنلاین نمی‌شه (۱ تا ۹۰ پیام).",
     [".automeow instant", ".automeow schedule 5", ".automeow off", ".میوخودکار instant"]),
    ("autofish", "🎣", "ماهیگیری خودکار", True,
     "ماهیگیری بازی میویی: غذا به پیشی (feed)، فروش مستقیم (sell) یا ذخیره در یخچال (fridge؛ "
     "یخچال پر بود ← فروش). لحظه‌ای یا زمان‌دار روی سرور تلگرام.",
     [".autofish feed schedule", ".autofish sell instant", ".autofish fridge schedule", ".autofish off"]),
    ("autofridge", "🧊", "یخچال خودکار", True,
     "پخت ماهی‌های خام یخچال میویی و بعد فروش یا غذا دادن به پیشی؛ زمان بعدی رو از زمان پخت "
     "حساب می‌کنه. یخچال خالی ← خواب خودکار.",
     [".autofridge sell schedule", ".autofridge feed instant", ".autofridge off"]),
    ("autobat", "🦇", "شکار خفاش", True,
     "وقتی پیام خفاش بازی میاد، ایموجی درستش (از روی کد خفاش) رو ریپلای می‌کنه. "
     "حالت دستی: ریپلای روی پیام خفاش + «batt».",
     [".autobat on", ".autobat delay 2", ".autobat list", "batt (روی ریپلای)"]),
    ("show", "👁", "حالت نمایش", False,
     "خاموش کردنش جواب دستورهای بازی (میو، ماهیگیری، یخچال، نجات، خفاش، الیاس) رو نشون نمی‌ده و "
     "خود دستور رو پاک می‌کنه؛ برای اینکه ادمین‌ها متوجه ربات بودن نشن.",
     [".show off", ".show on", ".نمایش off"]),
    ("sched", "⏰", "زمانبندی پیام", False,
     "چند پیام رو روی سرور تلگرام زمان‌بندی می‌کنه (اکانت آنلاین نمی‌شه). حداکثر ۱۰۰ پیام.",
     [".sched 10 5 میو", ".زمانبندی 3 60 سلام"]),
    ("alias", "🔗", "میانبر دستورات", False,
     "برای هر دستور یا متن یه اسم کوتاه بساز. آرگومان‌ها ($1 $2 $*) و زنجیره‌ی دستورها (&&) هم داره.",
     [".alias add am .automeow instant", ".alias list", ".alias del am", ".alias clear"]),
    ("proxy", "🌐", "پروکسی", False,
     "اتصال سلف به تلگرام از طریق پروکسی SOCKS5 / HTTP / MTProto (بعد از ریستارت اعمال می‌شه).",
     [".proxy set socks5://user:pass@host:1080", ".proxy off"]),
    ("status", "🩺", "وضعیت سلف", False,
     "مدت روشن بودن، حافظه، اتصال تلگرام، بات پنل، ذخیره‌سازی و تعداد قابلیت‌های روشن. "
     "هر بار که سلف ریستارت بشه، توی Saved Messages بهت خبر می‌ده (قابل خاموش شدن). "
     "«.وضعیت چت» وضعیت ماژول‌های بازی رو توی همون چت نشون می‌ده.",
     [".وضعیت", ".وضعیت چت", ".وضعیت اعلان off", ".وضعیت اعلان on"]),
    ("about", "📖", "درباره‌ی سلف", False,
     "سلف شخصی روی اکانت خودت؛ با Telethon نوشته شده و روی Railway اجرا می‌شه. "
     "تنظیمات توی /data ذخیره می‌شن. فقط خودت به پنل دسترسی داری.",
     [".راهنما", ".پنل"]),
]
FEATS = [
    {"key": k, "emoji": e, "name": n, "toggle": t, "desc": d, "examples": ex}
    for k, e, n, t, d, ex in _RAW
]
FEAT = {f["key"]: f for f in FEATS}

# چیدمان دکمه‌ها (هر ردیف از راست به چپ خونده می‌شه)
GRID = [
    ["canned", "clock", "guard"],
    ["locks", "action", "format"],
    ["filter", "ping", "logo"],
    ["forcejoin", "friends", "secretary"],
    ["react", "antidel", "autoreply"],
    ["delete", "savephoto", "download"],
    ["mute", "info", "block"],
    ["calc", "autoseen", "ai"],
    ["translate", "animation", "cheat"],
    ["tts", "videosearch", "news"],
    ["music", "mention", "afk"],
    ["online", "firstcomment", "currency"],
    ["date", "backup", "options"],
    ["status", "autotask", "autocatch"],
    ["automeow", "autofish", "autofridge"],
    ["autobat", "show", "sched"],
    ["alias", "proxy"],
    ["about"],
]
assert sorted(k for r in GRID for k in r) == sorted(FEAT), "GRID و FEATS یکی نیستن"

F = {f["key"]: (f["key"] == "clock") for f in FEATS if f["toggle"]}
CFG = {
    "target": os.getenv("CLOCK_TARGET", "last_name"),  # last_name | bio
    "font": os.getenv("CLOCK_FONT", "2"),
    "emoji": os.getenv("CLOCK_EMOJI", ""),  # خالی = بدون ایموجی
    "fmt": "bold",
    "afk_text": "الان آفلاینم، بعداً جواب می‌دم",
    "secretary_text": "سلام {name} 👋\nمنشی هستم؛ پیامت ثبت شد و بعداً جواب می‌دم.",
    "replies": {},
    "canned": {},
    "friends": [],
    "ignored": [],
    "chats": {},  # تنظیمات هر گروه: guard/locks/words/join/react/muted
    "fc_channels": {},
    "fc_text": "اول 🥇",
    "bot_token": os.getenv("BOT_TOKEN", ""),
    "panel_ttl": PANEL_TTL,  # حذف خودکار پنل داخل چت (ثانیه؛ 0 = بدون حذف)
    "panel_restrict": False,  # پنل فقط توی چت‌های مجاز نمایش داده بشه؟
    "panel_chats": [],  # چت‌های مجاز (Saved Messages همیشه مجازه)
    "theme": "classic",  # classic | mono | plain
    "afk_sched": "",  # ساعت سکوت، مثلاً 23:00-07:00
    "catch": {},  # {chat_id: {"word": "نجات", "delay": 1.0}}
    "autotasks": [],  # [{id, chat, kind: send|click, text, every(ثانیه), on}]
    "notify_restart": True,  # بعد از هر ریستارت توی Saved خبر بده
    "restarts": 0,
    "meow": {},  # تنظیمات بازی میویی: automeow/autofish/autofridge/bat/show/aliases (meow.py)
    "proxy": os.getenv("PROXY", ""),  # socks5://... | http://... | tg://proxy?... (بعد از ریستارت)
}
START_TIME = time.time()
state = {
    "authorized": False,
    "step": "phone",  # phone | code | 2fa
    "phone": None,
    "hash": None,
    "last_key": None,
    "me": None,  # آیدی عددی خودت
}
hooks = {}  # توابعی که ماژول‌ها برای هم ثبت می‌کنن (مثلاً refresh)
client = None  # TelegramClient فعلی

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
DATE_RE = re.compile(rf"\s*📅\s*{DIGITS}{{4}}/{DIGITS}{{2}}/{DIGITS}{{2}}\s*$")


# ───────────── ذخیره‌سازی ─────────────
def _write_json(path, data):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except OSError as e:
        log.warning("نمی‌تونم %s رو ذخیره کنم (Volume نذاشتی؟): %s", path, e)


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
    _write_json(API_FILE, API)


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return
    F.update({k: bool(v) for k, v in d.get("features", {}).items() if k in F})
    CFG.update({k: v for k, v in d.get("cfg", {}).items() if k in CFG})
    if not CFG["bot_token"]:
        CFG["bot_token"] = os.getenv("BOT_TOKEN", "")


def save_settings():
    _write_json(SETTINGS_FILE, {"features": F, "cfg": CFG})


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


# ───────────── تاریخ شمسی ─────────────
JM = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
      "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
JD = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]  # weekday(): Mon=0


def g2j(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy, gy = 979, gy - 1600
    else:
        jy, gy = 0, gy - 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            - 80 + gd + g_d_m[gm - 1])
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm, jd = 1 + days // 31, 1 + days % 31
    else:
        jm, jd = 7 + (days - 186) // 30, 1 + (days - 186) % 30
    return jy, jm, jd


def digits(s: str) -> str:
    return s.translate(FONTS.get(CFG["font"], FONTS["1"]))


def jalali_short() -> str:
    n = datetime.now(TZ)
    jy, jm, jd = g2j(n.year, n.month, n.day)
    return digits(f"{jy}/{jm:02d}/{jd:02d}")


def jalali_long() -> str:
    n = datetime.now(TZ)
    jy, jm, jd = g2j(n.year, n.month, n.day)
    return f"{JD[n.weekday()]} {jd} {JM[jm - 1]} {jy}"


def clock_text() -> str:
    t = digits(f"{datetime.now(TZ):%H:%M}")
    return f"{CFG['emoji']} {t}".strip()


def strip_clock(s: str) -> str:
    return CLOCK_RE.sub("", s or "").strip()


def strip_bio(s: str) -> str:
    prev = None
    while prev != s:
        prev = s
        s = DATE_RE.sub("", CLOCK_RE.sub("", s or "")).strip()
    return s


def profile_key():
    return (
        clock_text() if F["clock"] else "",
        jalali_short() if F["date"] else "",
        CFG["target"],
    )
