"""پنل وب (ورود با شماره/کد) + راه‌اندازی سلف."""
import boot  # noqa: F401  (باید اول باشه؛ نسخه‌ی بروزرسانی‌شده‌ی /data/code رو فعال می‌کنه)
import os

if __name__ == "__main__" and os.environ.get("HUB_BOT_TOKEN"):
    import hub  # حالت هاب: بات مشترک چندکاربره
    hub.main()
    raise SystemExit(0)
import hmac
import html
import asyncio

from aiohttp import web
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
from core import F, CFG, FEATS, FONTS, state, log, save_settings, save_api, save_session

TEMPLATE = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>پنل سلف</title>
<style>
body{font-family:system-ui,Tahoma,sans-serif;background:#0f1419;color:#e7e9ea;display:flex;
justify-content:center;padding:24px}
.card{background:#1a2129;border-radius:14px;padding:24px;width:100%;max-width:400px}
h2{margin-top:0}input,select,button{width:100%;padding:12px;margin:6px 0;border-radius:8px;
border:1px solid #2f3b47;background:#0f1419;color:#e7e9ea;font-size:16px;box-sizing:border-box}
button{background:#2a9df4;border:0;font-weight:bold;cursor:pointer}
button.red{background:#e0245e}.msg{background:#3b2a2a;padding:10px;border-radius:8px}
.ok{background:#1f3b2a}small{color:#8b98a5}
label.chk{display:flex;gap:10px;align-items:center;margin:8px 0}
label.chk input{width:auto;margin:0}
</style></head><body><div class="card">{{BODY}}</div></body></html>"""


def page(body: str, msg: str = "", ok: bool = False) -> web.Response:
    m = f'<p class="msg {"ok" if ok else ""}">{html.escape(msg)}</p>' if msg else ""
    return web.Response(text=TEMPLATE.replace("{{BODY}}", m + body), content_type="text/html")


def authed(request) -> bool:
    return hmac.compare_digest(request.cookies.get("auth", "").encode(), core.TOKEN.encode())


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


def opts(pairs, cur):
    return "".join(
        f'<option value="{html.escape(v)}" {"selected" if v == cur else ""}>{html.escape(t)}</option>'
        for v, t in pairs
    )


async def status_page(msg="", ok=False):
    me = await core.client.get_me()
    checks = "".join(
        f'<label class="chk"><input type="checkbox" name="f_{f["key"]}" '
        f'{"checked" if F[f["key"]] else ""}> {f["emoji"]} {html.escape(f["name"])}</label>'
        for f in FEATS if f["toggle"]
    )
    if botpanel.BOT["running"]:
        bot = f"✅ بات پنل وصله: @{html.escape(botpanel.BOT['username'] or '')} — توی تلگرام بزن .پنل"
    elif CFG["bot_token"]:
        bot = "⏳ توکن ثبت شده؛ در حال اتصال (یا توکن اشتباهه)"
    else:
        bot = "بات پنل تنظیم نشده. توکن رو از @BotFather بگیر و اینجا بذار."
    proxy_note = (f"🌐 پروکسی: {html.escape(meow.mask_proxy(CFG['proxy']))} (بعد از ریستارت اعمال می‌شه)"
                  if CFG.get("proxy") else "🌐 پروکسی: خاموش (روی Railway معمولاً لازم نیست)")
    body = f"""<h2>✅ وصل شدی</h2><p>{html.escape(me.first_name or '')}
<small dir="ltr">@{html.escape(me.username or '-')}</small></p>
<form method="post" action="/settings">{checks}
<select name="target">{opts([("last_name", "ساعت در فامیلی"), ("bio", "ساعت در بیو")], CFG['target'])}</select>
<select name="emoji">{opts([("", "بدون ایموجی"), ("⏰", "⏰"), ("🕒", "🕒"), ("⌚", "⌚")], CFG['emoji'])}</select>
<select name="font">{opts([(k, f"فونت {k}: {'12:34'.translate(v)}") for k, v in FONTS.items()], CFG['font'])}</select>
<hr><small>{bot}</small>
<input name="bot_token" placeholder="توکن بات پنل (BotFather)" dir="ltr" autocomplete="off">
<hr><small>{proxy_note}</small>
<input name="proxy" placeholder="پروکسی: socks5://user:pass@host:1080  (off = حذف)" dir="ltr" autocomplete="off">
<button>ذخیره</button></form>
<small>قابلیت‌های دستوری و پنل دکمه‌ای رنگی: توی تلگرام <b>.پنل</b> یا <b>.راهنما</b></small>
<form method="post" action="/logout"><button class="red">خروج از اکانت</button></form>"""
    return page(body, msg, ok)


async def index(request):
    if not authed(request):
        return page(F_PANEL)
    if core.client is None:
        return page(F_API)
    if state["authorized"]:
        return await status_page()
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
    phone = data["phone"].strip().replace(" ", "")
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
        return page(F_PHONE, f"خطا: {e}")
    state.update(phone=phone, hash=sent.phone_code_hash, step="code")
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
        web.post("/2fa", send_2fa),
        web.post("/settings", settings),
        web.post("/logout", logout),
    ])
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host="0.0.0.0", port=core.PORT)


if __name__ == "__main__":
    main()
