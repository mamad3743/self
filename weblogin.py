"""صفحه‌های ورود وب برای هاب: شماره ← کد ← رمز 2FA.

ورود با لینک یک‌بارمصرفی شروع می‌شه که بات هاب (یا مینی‌اپ) می‌ده؛ هویت کاربر از همون لینک معلومه.
مزیت: کد تلگرام توی فرم وب وارد می‌شه نه توی چت، پس تلگرام باطلش نمی‌کنه و خط تیره لازم نیست.
"""
import html

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


STEP_LABELS = ("شماره", "کد", "رمز", "وصل")
ROUTE_STEP = {"phone": 1, "code": 2, "pw": 3, "done": 5}
WARN = ("• اکانتت روی سرور این هاب اجرا می‌شه و سشن ورودت اونجا ذخیره می‌شه؛ یعنی ادمین سرور از نظر فنی به اون دسترسی داره.<br>"
        "• هر قابلیتی که روشن کنی از اکانت خودت اجرا می‌شه و مسئولیتش با خودته.<br>"
        "• هر وقت خواستی توی بات /disconnect بزن، یا از تلگرام ← Settings ← Devices نشستش رو ببند.")


def stepper(n: int) -> str:
    items = "".join(
        f'<li class="{"done" if i < n else ("cur" if i == n else "")}"><b>{"✓" if i < n else i}</b><span>{t}</span></li>'
        for i, t in enumerate(STEP_LABELS, 1))
    return f'<ol class="steps">{items}</ol>'


def page(body_html: str, msg: str = "", ok: bool = False, step: int = 0) -> str:
    m = f'<p class="msg {"ok" if ok else ""}">{html.escape(msg)}</p>' if msg else ""
    return TEMPLATE.replace("{{STEPS}}", stepper(step) if step else "").replace("{{BODY}}", m + body_html)


def _t(token: str) -> str:
    return f'<input type="hidden" name="t" value="{html.escape(token, quote=True)}">'


def invalid_page(bot_username: str = "") -> str:
    btn = (f'<a href="https://t.me/{html.escape(bot_username)}"><button type="button">🤖 باز کردن بات</button></a>'
           if bot_username else "")
    return page('<h2>⛔ لینک معتبر نیست</h2>'
                '<small>این لینک یک‌بارمصرفه و ۱۵ دقیقه اعتبار داره. توی بات <b>/connect</b> بزن و دوباره روی دکمه‌ی '
                '«ورود از صفحه‌ی وب» بزن.</small>' + btn)


def phone_page(token: str, msg: str = "", ok: bool = False, hint: str = "") -> str:
    return page(f"""<h2>📱 ورود به تلگرام</h2><form method="post" action="/login/phone">{_t(token)}
<input name="phone" placeholder="+989123456789" dir="ltr" inputmode="tel" autocomplete="tel" required autofocus>
<label class="chk"><input type="checkbox" name="consent"><span class="sw"></span><span class="t">شرایط زیر رو خوندم و قبول دارم</span></label>
<button>ارسال کد</button></form>
<small>{WARN}</small><small>شماره با کد کشور (+98…) یا مثل 0912…</small>
{('<small>' + html.escape(hint) + '</small>') if hint else ''}""", msg, ok, 1)


def code_page(token: str, notice: str = "", ok: bool = True, resend_label: str = "", msg: str = "") -> str:
    resend = (f'<form method="post" action="/login/resend">{_t(token)}<button class="ghost">🔁 {html.escape(resend_label)}</button></form>'
              if resend_label else f'<form method="post" action="/login/resend">{_t(token)}<button class="ghost">🔁 ارسال دوباره</button></form>')
    return page(f"""<h2>💬 کد تایید</h2><form method="post" action="/login/code">{_t(token)}
<input name="code" placeholder="کد تلگرام" dir="ltr" inputmode="numeric" autocomplete="one-time-code" required autofocus>
<button>تایید</button></form>{resend}
<small>✅ اینجا می‌تونی کد رو معمولی بنویسی؛ چون توی چت تلگرام نیست، باطل نمی‌شه و خط تیره لازم نداره.</small>""",
                msg or notice, ok if not msg else False, 2)


def pw_page(token: str, msg: str = "") -> str:
    return page(f"""<h2>🔑 رمز دو مرحله‌ای</h2><form method="post" action="/login/2fa">{_t(token)}
<input type="password" name="password" placeholder="رمز تایید دو مرحله‌ای" autocomplete="current-password" required autofocus>
<button>ورود</button></form>""", msg, False, 3)


def done_page(name: str, bot_username: str = "") -> str:
    btn = (f'<a href="https://t.me/{html.escape(bot_username)}"><button type="button">🤖 برگشت به بات</button></a>'
           if bot_username else "")
    return page(f"""<h2>✅ وصل شد</h2>
<div class="profile"><div class="avatar">{html.escape((name or "؟").strip()[:1])}</div><div><h3>{html.escape(name or "")}</h3>
<span class="u">اکانتت به هاب وصل شد</span></div><span class="live"><i></i>در حال اجرا</span></div>
<small>سلفت داره بالا میاد (حدود ۱۰ ثانیه). توی بات <b>/panel</b> و <b>/status</b> رو بزن؛ بعدش توی یه چت میویی <b>.میویی</b> یا <b>.ماهیگیری</b>.</small>{btn}""", "", False, 5)


def landing_page(bot_username: str = "") -> str:
    btn = (f'<a href="https://t.me/{html.escape(bot_username)}"><button type="button">🤖 باز کردن بات</button></a>'
           if bot_username else "")
    return page(f"""<h2>🔥 هاب سلف فعاله</h2>
<div class="chips"><span class="chip">✅ سرور در حال اجراست</span><span class="chip">📱 مینی‌اپ</span><span class="chip">🌐 ورود وب</span></div>
<small>برای وصل کردن اکانت:<br>۱) توی بات <b>/connect</b> بزن<br>۲) شرایط رو بپذیر و <b>«ورود از صفحه‌ی وب»</b> رو بزن<br>
۳) شماره و کد رو همین‌جا وارد کن.</small>{btn}""")
