"""پنل وب (ورود با شماره/کد) + راه‌اندازی سلف."""
import boot  # noqa: F401  (باید اول باشه؛ نسخه‌ی بروزرسانی‌شده‌ی /data/code رو فعال می‌کنه)
import os

if __name__ == "__main__" and os.environ.get("HUB_BOT_TOKEN"):
    import hub  # حالت هاب: بات مشترک چندکاربره
    hub.main()
    raise SystemExit(0)
import hmac
import html
import time
import asyncio

from aiohttp import web
from telethon.tl.functions.auth import ResendCodeRequest
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
    ApiIdInvalidError,
)

import core
import features
import botpanel
import meow
import updater
import ctl
import miniapp
from core import F, CFG, FEATS, FONTS, state, log, save_settings, save_api, save_session

TEMPLATE = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#07070a">
<title>پنل سلف · Erfan</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%94%A5%3C/text%3E%3C/svg%3E">
<style>
:root{--o1:#ff5a00;--o2:#ff8a1f;--o3:#ffc15e;--bg:#07070a;--card:#0e0e12;--card2:#15151b;--line:#2b2015;--txt:#f4efe9;--mut:#9a8f84;--glow:rgba(255,106,0,.35)}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;font-family:Vazirmatn,system-ui,-apple-system,"Segoe UI",Tahoma,sans-serif;color:var(--txt);background:var(--bg);overflow-x:hidden}
/* پس‌زمینه: توپ‌های نوری + شبکه + نویز */
.bg{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}
.orb{position:absolute;border-radius:50%;filter:blur(90px);opacity:.55;animation:float 14s ease-in-out infinite}
.o1{width:460px;height:460px;background:radial-gradient(circle,var(--o1),transparent 70%);top:-120px;right:-80px}
.o2{width:380px;height:380px;background:radial-gradient(circle,#ff2d00,transparent 70%);bottom:-140px;left:-100px;animation-delay:-5s;opacity:.4}
.o3{width:260px;height:260px;background:radial-gradient(circle,var(--o3),transparent 70%);top:42%;left:55%;animation-delay:-9s;opacity:.18}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(255,138,31,.07) 1px,transparent 1px),linear-gradient(90deg,rgba(255,138,31,.07) 1px,transparent 1px);background-size:44px 44px;-webkit-mask-image:radial-gradient(ellipse at 50% 35%,#000 20%,transparent 75%);mask-image:radial-gradient(ellipse at 50% 35%,#000 20%,transparent 75%)}
.noise{position:absolute;inset:0;opacity:.05;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
@keyframes float{0%,100%{transform:translate(0,0) scale(1)}50%{transform:translate(-30px,40px) scale(1.12)}}
.topbar{position:fixed;top:0;left:0;right:0;height:3px;z-index:5;background:linear-gradient(90deg,transparent,var(--o1),var(--o3),var(--o1),transparent);background-size:200% 100%;animation:slide 4s linear infinite}
@keyframes slide{to{background-position:-200% 0}}
.wrap{position:relative;z-index:2;min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:28px 16px 18px}
/* کارت */
.card{position:relative;width:100%;max-width:430px;background:linear-gradient(180deg,rgba(24,24,30,.92),rgba(12,12,16,.94));border:1px solid var(--line);border-radius:22px;padding:26px 24px 22px;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);box-shadow:0 0 0 1px rgba(255,138,31,.06),0 30px 80px -20px rgba(0,0,0,.9),0 0 60px -18px var(--glow);animation:rise .7s cubic-bezier(.2,.8,.2,1) both}
.card:before{content:"";position:absolute;inset:-1px;border-radius:23px;padding:1px;background:linear-gradient(135deg,rgba(255,138,31,.9),transparent 35%,transparent 65%,rgba(255,90,0,.7));-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;pointer-events:none}
@keyframes rise{from{opacity:0;transform:translateY(24px) scale(.98)}to{opacity:1;transform:none}}
/* برند */
.brand{display:flex;align-items:center;gap:14px;margin-bottom:18px}
.logo{width:54px;height:54px;flex:none;filter:drop-shadow(0 0 14px var(--glow));animation:pulse 3s ease-in-out infinite}
@keyframes pulse{50%{filter:drop-shadow(0 0 24px rgba(255,138,31,.65))}}
.brand h1{margin:0;font-size:22px;letter-spacing:.5px;font-weight:800;background:linear-gradient(90deg,var(--o3),var(--o1),var(--o3));background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:transparent;animation:shine 5s linear infinite}
@keyframes shine{to{background-position:200% center}}
.brand p{margin:3px 0 0;font-size:12.5px;color:var(--mut)}
.tag{margin-right:auto;font-size:10.5px;padding:4px 9px;border:1px solid rgba(255,138,31,.4);color:var(--o2);border-radius:99px;background:rgba(255,106,0,.08);letter-spacing:1px}
/* مراحل */
.steps{list-style:none;display:flex;justify-content:space-between;padding:0;margin:0 0 20px;position:relative}
.steps:before{content:"";position:absolute;top:13px;right:9%;left:9%;height:2px;background:#241a10}
.steps li{position:relative;z-index:1;display:flex;flex-direction:column;align-items:center;gap:6px;flex:1;font-size:11px;color:var(--mut)}
.steps b{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;font-size:12px;background:var(--card2);border:1px solid #33261a;color:var(--mut)}
.steps li.done b{background:linear-gradient(135deg,var(--o1),var(--o2));border-color:transparent;color:#140800}
.steps li.done{color:var(--o2)}
.steps li.cur b{background:#140a02;border-color:var(--o2);color:var(--o3);box-shadow:0 0 0 4px rgba(255,138,31,.15),0 0 18px var(--glow);animation:ring 2s ease-in-out infinite}
.steps li.cur{color:var(--txt);font-weight:700}
@keyframes ring{50%{box-shadow:0 0 0 7px rgba(255,138,31,.05),0 0 26px var(--glow)}}
/* متن‌ها و فرم */
h2{margin:0 0 14px;font-size:18px;font-weight:800;display:flex;align-items:center;gap:8px}
h2:after{content:"";flex:1;height:1px;background:linear-gradient(90deg,rgba(255,138,31,.5),transparent)}
form{margin:0}
input,select,button{width:100%;padding:13px 14px;margin:6px 0;border-radius:12px;border:1px solid #2c2118;background:#09090c;color:var(--txt);font-size:16px;font-family:inherit;outline:none;transition:border-color .2s,box-shadow .2s,transform .15s,background .2s}
input::placeholder{color:#6f655b}
input:focus,select:focus{border-color:var(--o2);box-shadow:0 0 0 3px rgba(255,138,31,.18),0 0 22px -6px var(--glow)}
button{position:relative;overflow:hidden;border:0;cursor:pointer;font-weight:800;letter-spacing:.2px;color:#170a00;background:linear-gradient(135deg,var(--o2),var(--o1));box-shadow:0 10px 26px -10px var(--glow)}
button:before{content:"";position:absolute;top:0;left:-120%;width:60%;height:100%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.35),transparent);transform:skewX(-20deg);transition:left .6s}
button:hover:before{left:140%}
button:hover{transform:translateY(-1px);box-shadow:0 14px 30px -10px rgba(255,106,0,.65)}
button:active{transform:translateY(1px) scale(.99)}
button.ghost{background:transparent;color:var(--o2);border:1px solid rgba(255,138,31,.45);box-shadow:none}
button.ghost:hover{background:rgba(255,138,31,.1);box-shadow:0 0 22px -8px var(--glow)}
button.red{background:transparent;color:#ff6b57;border:1px solid rgba(255,80,60,.45);box-shadow:none}
button.red:hover{background:rgba(255,60,40,.1);box-shadow:0 0 22px -8px rgba(255,60,40,.6)}
.msg{background:rgba(255,60,40,.1);border:1px solid rgba(255,80,60,.4);color:#ffb3a6;padding:11px 13px;border-radius:12px;font-size:14px;line-height:1.7;white-space:pre-line;margin:0 0 14px}
.msg.ok{background:rgba(255,138,31,.08);border-color:rgba(255,138,31,.4);color:var(--o3)}
small{display:block;color:var(--mut);font-size:12.5px;line-height:1.8;margin-top:6px}
hr{border:0;height:1px;background:linear-gradient(90deg,transparent,#33261a,transparent);margin:16px 0}
a{color:var(--o2);text-decoration:none}a:hover{color:var(--o3)}
/* وضعیت */
.profile{display:flex;align-items:center;gap:13px;padding:14px;border-radius:16px;background:linear-gradient(135deg,rgba(255,106,0,.12),rgba(255,106,0,.02));border:1px solid rgba(255,138,31,.25);margin-bottom:14px}
.avatar{width:50px;height:50px;border-radius:15px;display:grid;place-items:center;font-size:22px;font-weight:800;color:#170a00;background:linear-gradient(135deg,var(--o3),var(--o1));box-shadow:0 8px 22px -8px var(--glow)}
.profile h3{margin:0;font-size:17px}.profile .u{font-size:12.5px;color:var(--mut)}
.live{margin-right:auto;display:flex;align-items:center;gap:7px;font-size:12px;color:#7dffb0}
.live i{width:8px;height:8px;border-radius:50%;background:#2cff85;box-shadow:0 0 0 0 rgba(44,255,133,.6);animation:blink 1.8s infinite}
@keyframes blink{70%{box-shadow:0 0 0 9px rgba(44,255,133,0)}100%{box-shadow:0 0 0 0 rgba(44,255,133,0)}}
.chips{display:flex;flex-wrap:wrap;gap:7px;margin-bottom:6px}
.chip{font-size:12px;padding:6px 11px;border-radius:99px;background:var(--card2);border:1px solid #2b2015;color:#d6cabd}
.chip b{color:var(--o2)}
.sec{margin:18px 0 8px;font-size:12px;letter-spacing:.6px;color:var(--o2);font-weight:700;display:flex;align-items:center;gap:8px}
.sec:after{content:"";flex:1;height:1px;background:#2a1f15}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
label.chk{position:relative;display:flex;align-items:center;gap:10px;padding:10px 11px;margin:0;border-radius:12px;background:var(--card2);border:1px solid #261c13;cursor:pointer;font-size:13px;transition:border-color .2s,background .2s,transform .15s;user-select:none}
label.chk:hover{border-color:rgba(255,138,31,.5);transform:translateY(-1px)}
label.chk input{position:absolute;opacity:0;width:0;height:0;margin:0;padding:0}
.sw{flex:none;width:34px;height:20px;border-radius:99px;background:#2a2118;position:relative;transition:background .25s,box-shadow .25s}
.sw:after{content:"";position:absolute;top:2px;right:2px;width:16px;height:16px;border-radius:50%;background:#7a6e62;transition:transform .25s,background .25s}
label.chk input:checked~.sw{background:linear-gradient(135deg,var(--o2),var(--o1));box-shadow:0 0 14px -2px var(--glow)}
label.chk input:checked~.sw:after{transform:translateX(-14px);background:#fff}
label.chk:has(input:checked){border-color:rgba(255,138,31,.55);background:linear-gradient(135deg,rgba(255,106,0,.13),var(--card2))}
label.chk input:focus-visible~.sw{outline:2px solid var(--o3);outline-offset:2px}
.t{line-height:1.35}
select{appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%23ff8a1f' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:14px 50%;padding-left:38px;cursor:pointer}
/* امضا */
.credit{position:relative;z-index:2;margin-top:18px;text-align:center;font-size:13px;color:var(--mut)}
.credit .by{display:inline-flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:6px 10px;padding:9px 16px;max-width:100%;border-radius:99px;background:rgba(14,14,18,.8);border:1px solid #2b2015;backdrop-filter:blur(8px)}
.credit b{background:linear-gradient(90deg,var(--o3),var(--o1));-webkit-background-clip:text;background-clip:text;color:transparent;font-weight:800}
.credit .by>span{white-space:nowrap}
.credit .sep{width:4px;height:4px;border-radius:50%;background:var(--o1)}
.credit a{direction:ltr;unicode-bidi:embed;font-weight:700}
.credit .ver{display:block;margin-top:8px;font-size:11px;opacity:.55;letter-spacing:1px}
@media(max-width:420px){.card{padding:22px 16px 18px}.grid2{grid-template-columns:1fr}.credit .sep{display:none}.credit .by{border-radius:16px;flex-direction:column;gap:3px}.steps li span{font-size:10px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
</style></head><body>
<div class="topbar"></div>
<div class="bg"><i class="orb o1"></i><i class="orb o2"></i><i class="orb o3"></i><div class="grid"></div><div class="noise"></div></div>
<main class="wrap">
<div class="card">
<header class="brand">
<svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffc15e"/><stop offset=".55" stop-color="#ff7a10"/><stop offset="1" stop-color="#ff3d00"/></linearGradient></defs>
<path d="M32 3 57 17.5v29L32 61 7 46.5v-29z" fill="#120a03" stroke="url(#g)" stroke-width="2.5" stroke-linejoin="round"/>
<path d="M36.5 12 20 35h10.5L27 52l17-24H33.2z" fill="url(#g)"/></svg>
<div><h1>SELF PANEL</h1><p>سلف تلگرام · بازی میویی · کنترل کامل</p></div>
<span class="tag">v2</span>
</header>
{{STEPS}}{{BODY}}
</div>
<footer class="credit"><span class="by"><span>ساخته شده توسط <b>عرفان</b></span><i class="sep"></i><span>آیدی تلگرام <a href="https://t.me/mamadi1048" target="_blank" rel="noopener">@mamadi1048</a></span></span>
<span class="ver">ERFAN · SELF · 2026</span></footer>
</main></body></html>"""

STEP_LABELS = ("پنل", "API", "شماره", "کد", "وصل")


def stepper(n: int) -> str:
    """n = مرحله‌ی فعلی (۱ تا ۵)؛ ۶ = همه انجام شده."""
    items = "".join(
        f'<li class="{"done" if i < n else ("cur" if i == n else "")}"><b>{"✓" if i < n else i}</b><span>{t}</span></li>'
        for i, t in enumerate(STEP_LABELS, 1))
    return f'<ol class="steps">{items}</ol>'


def infer_step(body: str) -> int:
    for marker, n in (('action="/panel"', 1), ('action="/api"', 2), ('action="/phone"', 3), ('action="/code"', 4),
                      ('action="/2fa"', 4), ('action="/settings"', 6)):
        if marker in body:
            return n
    return 0


def page(body: str, msg: str = "", ok: bool = False, step=None) -> web.Response:
    m = f'<p class="msg {"ok" if ok else ""}">{html.escape(msg)}</p>' if msg else ""
    n = infer_step(body) if step is None else step
    html_ = TEMPLATE.replace("{{STEPS}}", stepper(n) if n else "").replace("{{BODY}}", m + body)
    return web.Response(text=html_, content_type="text/html")


def authed(request) -> bool:
    return hmac.compare_digest(request.cookies.get("auth", "").encode(), core.TOKEN.encode())


F_PANEL = """<h2>🔐 ورود به پنل</h2><form method="post" action="/panel">
<input type="password" name="password" placeholder="رمز پنل" required autofocus><button>ورود به پنل</button></form>
<small>رمز همون متغیر PANEL_PASSWORD توی تنظیمات سرورته.</small>"""

F_API = """<h2>⚙️ اطلاعات API</h2><form method="post" action="/api">
<input name="api_id" placeholder="API ID (عدد)" dir="ltr" inputmode="numeric" required>
<input name="api_hash" placeholder="API Hash" dir="ltr" required>
<button>ذخیره و ادامه</button></form><small>از my.telegram.org ← API development tools</small>"""

F_PHONE = """<h2>📱 ورود به تلگرام</h2><form method="post" action="/phone">
<input name="phone" placeholder="+989123456789" dir="ltr" inputmode="tel" required autofocus>
<button>ارسال کد</button></form><small>شماره با کد کشور (+98...) یا مثل 0912...؛ کد برات فرستاده می‌شه.</small>"""

F_CODE = """<h2>💬 کد تایید</h2><form method="post" action="/code">
<input name="code" placeholder="کد ۵ رقمی" dir="ltr" inputmode="numeric" required autofocus>
<button>تایید</button></form>
<form method="post" action="/resend"><button class="ghost">🔁 ارسال دوباره / روش بعدی</button></form>
<small>کد رو با فاصله یا خط تیره بنویس (مثلاً 1-2-3-4-5)؛ پشت‌سرهم نوشتنش باعث باطل شدن کد می‌شه.</small>"""

F_2FA = """<h2>🔑 رمز دو مرحله‌ای</h2><form method="post" action="/2fa">
<input type="password" name="password" placeholder="رمز تایید دو مرحله‌ای" required autofocus>
<button>ورود</button></form>"""


def opts(pairs, cur):
    return "".join(
        f'<option value="{html.escape(v)}" {"selected" if v == cur else ""}>{html.escape(t)}</option>'
        for v, t in pairs
    )


async def status_page(msg="", ok=False):
    me = await core.client.get_me()
    toggles = [f for f in FEATS if f["toggle"]]
    on = sum(1 for f in toggles if F[f["key"]])
    checks = "".join(
        f'<label class="chk"><input type="checkbox" name="f_{f["key"]}" {"checked" if F[f["key"]] else ""}>'
        f'<span class="sw"></span><span class="t">{f["emoji"]} {html.escape(f["name"])}</span></label>'
        for f in toggles
    )
    if botpanel.BOT["running"]:
        bot = f"✅ بات پنل وصله: @{html.escape(botpanel.BOT['username'] or '')} — توی تلگرام بزن .پنل"
        bot_chip = "🤖 بات پنل: <b>وصل</b>"
    elif CFG["bot_token"]:
        bot = "⏳ توکن ثبت شده؛ در حال اتصال (یا توکن اشتباهه)"
        bot_chip = "🤖 بات پنل: <b>در حال اتصال</b>"
    else:
        bot = "بات پنل تنظیم نشده. توکن رو از @BotFather بگیر و اینجا بذار."
        bot_chip = "🤖 بات پنل: <b>تنظیم نشده</b>"
    proxy_note = (f"🌐 پروکسی: {html.escape(meow.mask_proxy(CFG['proxy']))} (بعد از ریستارت اعمال می‌شه)"
                  if CFG.get("proxy") else "🌐 پروکسی: خاموش (روی Railway معمولاً لازم نیست)")
    initial = html.escape((me.first_name or me.username or "?").strip()[:1].upper() or "?")
    body = f"""<div class="profile"><div class="avatar">{initial}</div>
<div><h3>{html.escape(me.first_name or '')}</h3><span class="u" dir="ltr">@{html.escape(me.username or '-')}</span></div>
<span class="live"><i></i>متصل</span></div>
<div class="chips"><span class="chip">🎛 <b>{on}</b> از {len(toggles)} قابلیت روشن</span><span class="chip">{bot_chip}</span>
<span class="chip">⚡ {len(FEATS)} دستور</span></div>
<form method="post" action="/settings">
<div class="sec">قابلیت‌ها</div><div class="grid2">{checks}</div>
<div class="sec">نمایش ساعت</div>
<select name="target">{opts([("last_name", "ساعت در فامیلی"), ("bio", "ساعت در بیو")], CFG['target'])}</select>
<select name="emoji">{opts([("", "بدون ایموجی"), ("⏰", "⏰"), ("🕒", "🕒"), ("⌚", "⌚")], CFG['emoji'])}</select>
<select name="font">{opts([(k, f"فونت {k}: {'12:34'.translate(v)}") for k, v in FONTS.items()], CFG['font'])}</select>
<div class="sec">بات پنل</div><small>{bot}</small>
<input name="bot_token" placeholder="123456789:AAH-bot-token" dir="ltr" autocomplete="off" spellcheck="false">
<div class="sec">پروکسی</div><small>{proxy_note}</small>
<input name="proxy" placeholder="socks5://user:pass@host:1080" dir="ltr" autocomplete="off" spellcheck="false">
<small>برای حذف پروکسی <b>off</b> بنویس.</small>
<button>💾 ذخیره‌ی تنظیمات</button></form>
<small>قابلیت‌های دستوری و پنل دکمه‌ای رنگی: توی تلگرام <b>.پنل</b> یا <b>.راهنما</b></small>
<hr><form method="post" action="/logout"><button class="red">خروج از اکانت</button></form>"""
    return page(body, msg, ok)


async def index(request):
    if not authed(request):
        return page(F_PANEL)
    if core.client is None:
        return page(F_API)
    if state["authorized"]:
        return await status_page()
    if state["step"] == "code":
        return page(F_CODE, state.get("notice", ""), True)
    if state["step"] == "phone" and core.api_hint():
        return page(F_PHONE + f"<small>{html.escape(core.api_hint())}</small>")
    return page({"phone": F_PHONE, "code": F_CODE, "2fa": F_2FA}[state["step"]])


async def panel_login(request):
    data = await request.post()
    if hmac.compare_digest(data.get("password", "").encode(), core.PANEL_PASSWORD.encode()):
        resp = web.HTTPFound("/")
        resp.set_cookie("auth", core.TOKEN, httponly=True, secure=True, max_age=86400 * 30)
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
    data = await request.post()
    try:
        api_id = int(data["api_id"].strip())
    except ValueError:
        return page(F_API, "API ID باید عدد باشه")
    core.API.update(id=api_id, hash=data["api_hash"].strip())
    save_api()
    core.client = features.make_client()
    await core.client.connect()
    state.update(authorized=False, step="phone")
    raise web.HTTPFound("/")


@need_auth
async def send_phone(request):
    data = await request.post()
    phone = core.normalize_phone(data["phone"])
    if not phone:
        return page(F_PHONE, "شماره معتبر نیست؛ مثلاً +989121234567 یا 09121234567")
    try:
        sent = await core.client.send_code_request(phone)
    except ApiIdInvalidError:
        await core.client.disconnect()
        core.client = None
        core.API.update(id=0, hash="")
        try:
            os.remove(core.API_FILE)
        except OSError:
            pass
        return page(F_API, "API ID یا API Hash اشتباهه، دوباره وارد کن")
    except Exception as e:  # noqa
        log.warning("send_code failed: %r", e)
        return page(F_PHONE, f"خطا: {type(e).__name__}: {e}" + (f"\n{core.api_hint()}" if core.api_hint() else ""))
    state.update(phone=phone, hash=sent.phone_code_hash, step="code", notice=code_notice(sent))
    raise web.HTTPFound("/")


def code_notice(sent) -> str:
    how, nxt = core.sent_code_info(sent)
    return f"کد فرستاده شد: {how}" + (f" — اگه نیومد «ارسال دوباره» رو بزن ({nxt})" if nxt else "") + \
        (f"\n{core.api_hint()}" if core.api_hint() else "")


@need_auth
async def resend(request):
    if state.get("step") != "code" or not state.get("phone"):
        raise web.HTTPFound("/")
    try:
        sent = await core.client(ResendCodeRequest(state["phone"], state["hash"]))
    except Exception as e:  # noqa
        log.warning("resend failed: %r", e)
        return page(F_CODE, f"ارسال دوباره ممکن نشد: {type(e).__name__}: {e}")
    state.update(hash=sent.phone_code_hash, notice="🔁 دوباره فرستاده شد. " + code_notice(sent))
    raise web.HTTPFound("/")


async def finish_login():
    save_session()
    state.update(authorized=True, step="phone", last_key=None)
    await features.set_me()
    log.info("Login OK")


@need_auth
async def send_code(request):
    data = await request.post()
    code = data["code"].strip().replace(" ", "")
    try:
        await core.client.sign_in(state["phone"], code, phone_code_hash=state["hash"])
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
        await core.client.sign_in(password=data["password"])
    except PasswordHashInvalidError:
        return page(F_2FA, "رمز اشتباهه")
    except Exception as e:  # noqa
        return page(F_2FA, f"خطا: {e}")
    await finish_login()
    raise web.HTTPFound("/")


@need_auth
async def settings(request):
    data = await request.post()
    for f in FEATS:
        if f["toggle"]:
            F[f["key"]] = data.get(f"f_{f['key']}") == "on"
    CFG["target"] = data.get("target", "last_name")
    CFG["emoji"] = data.get("emoji", "")
    CFG["font"] = data.get("font", "2")
    tok = data.get("bot_token", "").strip()
    if tok:
        CFG["bot_token"] = tok
    prx = data.get("proxy", "").strip()
    if prx.lower() in ("off", "-", "خاموش"):
        CFG["proxy"] = ""
    elif prx and meow.parse_proxy_link(prx):
        CFG["proxy"] = prx
    elif prx:
        return await status_page("آدرس پروکسی معتبر نیست", ok=False)
    save_settings()
    await features.refresh()
    return await status_page("ذخیره شد", ok=True)


@need_auth
async def logout(request):
    try:
        await features.sync_profile(clean=True)
        await core.client.log_out()
    except Exception as e:  # noqa
        log.warning("logout: %s", e)
    try:
        os.remove(core.SESSION_FILE)
    except OSError:
        pass
    core.client = features.make_client()
    await core.client.connect()
    state.update(authorized=False, step="phone", me=None)
    raise web.HTTPFound("/")


# ───────────── مینی‌اپ تک‌سلف (همون مینی‌اپ هاب، با همین بک‌اند) ─────────────
# احراز: کوکی پنل وب (مثل بقیه‌ی پنل) یا initData تلگرام (با توکن بات خودت).
# با .پنل توی هر چتی دکمه‌ی باز کردنش میاد.
_ME_CACHE = {"t": 0.0, "me": None}


def mini_authed(request) -> bool:
    try:
        return hmac.compare_digest(request.cookies.get("auth", "").encode(), core.TOKEN.encode())
    except Exception:  # noqa
        return False


async def mini_body(request):
    """بادی درخواست اگه احراز باشه، وگرنه None (کوکی یا initData)."""
    if mini_authed(request):
        try:
            return await request.json()
        except Exception:  # noqa
            return {}
    try:
        body = await request.json()
    except Exception:  # noqa
        return None
    if not isinstance(body, dict):
        return None
    tok = (CFG.get("bot_token") or "").strip()
    uid = miniapp.verify(body.get("initData", ""), tok) if tok else None
    if uid and state.get("me") and uid == state.get("me"):
        return body
    return None


def mini_need_auth():
    return web.json_response(
        {"ok": False, "error": "وارد نشدی؛ اول از پنل وب همین دامنه وارد شو یا مینی‌اپ رو از دکمه‌ی بات باز کن"},
        status=401)


async def mini_me_cached():
    if time.time() - _ME_CACHE["t"] < 120 and _ME_CACHE["me"] is not None:
        return _ME_CACHE["me"]
    try:
        me = await core.client.get_me()
    except Exception:  # noqa
        return None
    _ME_CACHE.update(t=time.time(), me=me)
    return me


async def single_snapshot():
    me = await mini_me_cached() if state.get("authorized") else None
    loops = {}
    try:
        for kind, cid in meow.TASKS:
            loops[kind] = loops.get(kind, 0) + 1
    except Exception:  # noqa
        pass
    feats = [{"key": f["key"], "name": f["name"], "emoji": f["emoji"], "toggle": f["toggle"],
              "on": bool(F.get(f["key"])), "desc": f["desc"]} for f in FEATS]
    on = sum(1 for f in feats if f["toggle"] and f["on"])
    mem = None
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    mem = round(int(line.split()[1]) / 1024)
                    break
    except OSError:
        pass
    pend = 0
    try:
        now = time.time()
        nxt = (meow.M().get("next") or {})
        pend = sum(1 for v in nxt.values() if isinstance(v, (int, float)) and v > now)
    except Exception:  # noqa
        pass
    account = None
    if me is not None:
        nm = " ".join(x for x in [getattr(me, "first_name", None), getattr(me, "last_name", None)] if x)
        account = {"name": nm or getattr(me, "username", None) or "—",
                   "username": getattr(me, "username", None), "id": getattr(me, "id", None)}
    return {"ok": True, "connected": bool(state.get("authorized")), "mode": "single",
            "caps": {"run_stop": False, "restore_last": False},
            "me": account, "sub": None, "domain": "",
            "running": bool(state.get("authorized")), "failed": False,
            "uptime": int(time.time() - core.START_TIME) if state.get("authorized") else 0,
            "ram": mem, "restarts": CFG.get("restarts", 0), "pending": pend,
            "authorized": bool(state.get("authorized")), "loops": loops,
            "on_count": on, "total": len(feats), "feats": feats}


async def mini_app_page(request):
    return web.Response(text=miniapp.HTML, content_type="text/html")


async def mini_api_me(request):
    if await mini_body(request) is None:
        return mini_need_auth()
    if not state.get("authorized"):
        return web.json_response({"ok": True, "connected": False, "mode": "single",
                                  "hint": "هنوز وارد تلگرام نشدی؛ اول از پنل وب همین دامنه وارد شو",
                                  "sub": None, "caps": {"run_stop": False, "restore_last": False},
                                  "me": None})
    return web.json_response(await single_snapshot())


async def mini_api_toggle(request):
    body = await mini_body(request)
    if body is None:
        return mini_need_auth()
    key = (body.get("key") or "")
    if key not in F:
        return web.json_response({"ok": False, "error": "کلید نامعتبره"}, status=400)
    await ctl.handle({"op": "toggle", "key": key, "value": bool(body.get("value"))})
    return web.json_response(await single_snapshot())


async def mini_api_control(request):
    body = await mini_body(request)
    if body is None:
        return mini_need_auth()
    act = str(body.get("action", "")).lower()
    if act == "restart":
        async def _late():
            await asyncio.sleep(2)
            updater.restart()
        asyncio.create_task(_late())
        d = await single_snapshot()
        d["msg"] = "🔄 سلف داره ریستارت می‌شه؛ چند ثانیه بعد رفرش کن"
        return web.json_response(d)
    if act == "run":
        d = await single_snapshot()
        d["msg"] = "🟢 تک‌سلف همیشه روشنه"
        return web.json_response(d)
    return web.json_response({"ok": False, "error": "توقف سلف از مینی‌اپ ممکن نیست"}, status=400)


async def mini_api_cmd(request):
    body = await mini_body(request)
    if body is None:
        return mini_need_auth()
    target = str(body.get("target", "me")).strip() or "me"
    text = str(body.get("text", "")).strip()[:500]
    if not text:
        return web.json_response({"ok": False, "error": "دستور خالیه"}, status=400)
    if target.lower() != "me" and not (target.startswith("@") or target.lstrip("-").isdigit()):
        return web.json_response({"ok": False, "error": "هدف باید me یا @username یا آیدی عددی باشه"}, status=400)
    if not (state.get("authorized") and core.client):
        return web.json_response({"ok": False, "error": "سلف وارد نشده"}, status=400)
    await ctl.handle({"op": "run", "chat": target, "text": text})
    return web.json_response({"ok": True, "msg": f"✅ به {target} فرستاده شد"})


def mini_sanitized():
    cfg = {k: v for k, v in CFG.items() if k not in ("bot_token", "proxy")}
    return {"features": {k: bool(v) for k, v in F.items()}, "cfg": cfg}


async def mini_api_backup(request):
    if await mini_body(request) is None:
        return mini_need_auth()
    return web.json_response({"ok": True, "backup": mini_sanitized()})


async def mini_api_restore(request):
    body = await mini_body(request)
    if body is None:
        return mini_need_auth()
    obj = (body or {}).get("backup")
    if not isinstance(obj, dict) or not isinstance(obj.get("features"), dict) or not isinstance(obj.get("cfg"), dict):
        return web.json_response({"ok": False, "error": "ساختار بکاپ درست نیست"}, status=400)
    feats = {k: bool(v) for k, v in obj["features"].items() if k in F}
    cfg = {k: v for k, v in obj["cfg"].items() if k in CFG and k not in ("bot_token", "proxy")}
    F.update(feats)
    CFG.update(cfg)
    save_settings()
    try:
        await features.refresh()
    except Exception:  # noqa
        pass
    try:
        await meow.ensure()
    except Exception:  # noqa
        pass
    d = await single_snapshot()
    d["msg"] = f"✅ {len(feats)} قابلیت و {len(cfg)} تنظیم برگشت"
    return web.json_response(d)


async def on_startup(app):
    core.load_api()
    core.load_settings()
    ctl.prepare()
    if core.API["id"] and core.API["hash"]:
        core.client = features.make_client(core.load_session())
        await core.client.connect()
        state["authorized"] = await core.client.is_user_authorized()
        if state["authorized"]:
            await features.set_me()
    log.info("authorized=%s", state["authorized"])
    if state["authorized"]:
        asyncio.create_task(features.notify_start())
    app["tasks"] = [
        asyncio.create_task(features.clock_loop()),
        asyncio.create_task(features.online_loop()),
        asyncio.create_task(features.auto_loop()),
        asyncio.create_task(meow.supervisor()),
        asyncio.create_task(updater.mark_healthy()),
        asyncio.create_task(botpanel.run()),
    ]
    if ctl.CTL:
        app["tasks"].append(asyncio.create_task(ctl.loop()))


async def on_cleanup(app):
    for t in list(meow.TASKS.values()):  # اول حلقه‌های بازی بسته بشن؛ موقع دیپلوی/ریستارت پیام آخر نفرستن
        t.cancel()
    for t in app["tasks"]:
        t.cancel()
    if core.client:
        await core.client.disconnect()


def main():
    app = web.Application()
    app.add_routes([
        web.get("/", index),
        web.post("/panel", panel_login),
        web.post("/api", send_api),
        web.post("/phone", send_phone),
        web.post("/code", send_code),
        web.post("/resend", resend),
        web.post("/2fa", send_2fa),
        web.post("/settings", settings),
        web.post("/logout", logout),
        web.get("/app", mini_app_page),
        web.post("/api/me", mini_api_me),
        web.post("/api/toggle", mini_api_toggle),
        web.post("/api/control", mini_api_control),
        web.post("/api/cmd", mini_api_cmd),
        web.post("/api/backup", mini_api_backup),
        web.post("/api/restore", mini_api_restore),
    ])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host="0.0.0.0", port=core.PORT)


if __name__ == "__main__":
    main()
