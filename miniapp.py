"""مینی‌اپ مشترک سلف (تک‌سورس برای حالت هاب و تک‌سلف).

- `HTML`: صفحه‌ی مینی‌اپ؛ با `/api/*` همین هاست حرف می‌زنه.
- شکل اسنپ‌شات مورد انتظار از `/api/me` (هر دو حالت):
  {ok, connected, mode, caps:{run_stop, restore_last},
   me:{name, username, id} | null, sub:str | null, domain:str,
   running, failed, uptime, ram, restarts, pending, authorized, loops,
   on_count, total, feats:[{key,name,emoji,toggle,on,desc}]}
- `domain()` / `app_url()` / `web_url()`: دامنه‌ی عمومی از روی متغیرها.
- `verify()`: اعتبارسنجی initData تلگرام با توکن بات (خروجی: user_id یا None).
"""
import os


def domain() -> str:
    d = (os.getenv("HUB_DOMAIN") or os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip().rstrip("/")
    if d and not d.startswith("http"):
        d = "https://" + d
    return d


def app_url() -> str:
    d = domain()
    return d + "/app" if d else ""


def web_url() -> str:
    d = domain()
    return d + "/" if d else ""


def verify(init_data: str, bot_token: str, max_age: int = 86400):
    """initData تلگرام رو با توکن بات چک می‌کنه؛ user_id یا None."""
    import hmac
    import hashlib
    import json
    import time
    import urllib.parse

    try:
        params = dict(urllib.parse.parse_qsl(init_data or "", keep_blank_values=True))
        recv_hash = params.pop("hash", "")
        if not recv_hash or not bot_token:
            return None
        data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv_hash):
            return None
        try:
            auth_date = int(params.get("auth_date", "0"))
            if auth_date and time.time() - auth_date > max_age:
                return None
        except ValueError:
            return None
        user = json.loads(params.get("user", "{}"))
        uid = int(user.get("id", 0))
        return uid or None
    except Exception:  # noqa
        return None


HTML = """<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<title>سلف · مینی‌اپ</title>
<style>
:root{--o1:#ff5a00;--o2:#ff8a1f;--o3:#ffc15e;--bg:#07070a;--card:#101014;--card2:#17171e;--line:#2b2015;--txt:#f4efe9;--mut:#9a8f84;--glow:rgba(255,106,0,.35);--grn:#2cff85;--red:#ff6b57}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;font-family:system-ui,Vazirmatn,Tahoma,sans-serif;color:var(--txt);padding:0 0 46px;min-height:100vh;background:radial-gradient(600px 300px at 85% -60px,rgba(255,106,0,.16),transparent 70%),radial-gradient(500px 260px at 0% 0%,rgba(255,45,0,.1),transparent 65%),var(--bg)}
.topbar{height:3px;background:linear-gradient(90deg,transparent,var(--o1),var(--o3),var(--o1),transparent);background-size:200% 100%;animation:slide 4s linear infinite}
@keyframes slide{to{background-position:-200% 0}}
.wrap{padding:14px 12px 0;max-width:560px;margin:0 auto}
.brand{display:flex;align-items:center;gap:10px;margin:6px 0 2px}
.logo{width:40px;height:40px;flex:none;filter:drop-shadow(0 0 12px var(--glow))}
h1{font-size:19px;margin:0;background:linear-gradient(90deg,var(--o3),var(--o1));-webkit-background-clip:text;background-clip:text;color:transparent;font-weight:800}
.sub{color:var(--mut);font-size:12px;margin:2px 0 10px;line-height:1.8}
.card{background:linear-gradient(180deg,rgba(26,26,32,.95),rgba(13,13,17,.95));border:1px solid var(--line);border-radius:16px;padding:13px;margin:10px 0;box-shadow:0 14px 40px -18px rgba(0,0,0,.9),0 0 40px -20px var(--glow)}
.card h3{margin:0 0 8px;font-size:14px;display:flex;align-items:center;gap:8px}
.card h3:after{content:"";flex:1;height:1px;background:linear-gradient(90deg,rgba(255,138,31,.4),transparent)}
.me{display:flex;align-items:center;gap:11px}
.avatar{width:48px;height:48px;flex:none;border-radius:15px;display:grid;place-items:center;font-size:21px;font-weight:800;color:#170a00;background:linear-gradient(135deg,var(--o3),var(--o1));box-shadow:0 8px 22px -8px var(--glow)}
.me h2{margin:0;font-size:16px}.me .u{font-size:12px;color:var(--mut);direction:ltr;unicode-bidi:embed}
.live{margin-right:auto;display:flex;align-items:center;gap:7px;font-size:12px;color:#7dffb0;white-space:nowrap}
.live.off{color:#ff8d7d}.live i{width:8px;height:8px;border-radius:50%;background:#2cff85;box-shadow:0 0 0 0 rgba(44,255,133,.6);animation:blink 1.8s infinite}
.live.off i{background:#ff6b57;animation:none}
@keyframes blink{70%{box-shadow:0 0 0 8px rgba(44,255,133,0)}100%{box-shadow:0 0 0 0 rgba(44,255,133,0)}}
.row{display:flex;gap:8px;flex-wrap:wrap}button{flex:1;min-width:100px;padding:11px;border-radius:11px;border:1px solid var(--line);background:#1e1e26;color:var(--txt);font-size:14px;font-weight:700;cursor:pointer;transition:transform .12s,box-shadow .2s}
button:active{transform:scale(.98)}
button.on{background:linear-gradient(135deg,var(--o2),var(--o1));color:#170a00;border:0;box-shadow:0 8px 22px -10px var(--glow)}
button.danger{border-color:rgba(255,80,60,.5);color:#ff8d7d;background:transparent}
button.ghost{background:transparent}button:disabled{opacity:.45}
button.busy{opacity:.55;pointer-events:none}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}.f{display:flex;align-items:center;gap:8px;background:#101016;border:1px solid var(--line);border-radius:11px;padding:9px;font-size:13px;cursor:pointer;transition:border-color .2s,transform .12s}
.f:active{transform:scale(.98)}.f b{margin-right:auto;font-size:11px;font-weight:700}.f.on{border-color:rgba(255,138,31,.6);background:linear-gradient(135deg,rgba(255,106,0,.12),#101016)}
.dot{width:9px;height:9px;flex:none;border-radius:50%;background:#555}.f.on .dot{background:var(--grn);box-shadow:0 0 8px var(--grn)}
.f .st-off{color:var(--mut)}.f.on .st-off{color:var(--grn)}
input,select,textarea{width:100%;padding:10px;margin:5px 0;border-radius:10px;border:1px solid var(--line);background:#0c0c10;color:var(--txt);font-size:14px;font-family:inherit;outline:none}
input:focus,textarea:focus{border-color:var(--o2);box-shadow:0 0 0 3px rgba(255,138,31,.15)}
small{color:var(--mut);font-size:12px;line-height:1.9}.ok{color:#7dffb0}.err{color:#ff8d7d}
.tabs{display:flex;gap:6px;margin:10px 0;position:sticky;top:0;z-index:2;background:rgba(7,7,10,.9);padding:8px 0;backdrop-filter:blur(8px)}
.tabs button{font-size:13px;padding:10px 6px}
.hidden{display:none}.pill{font-size:11px;background:#22222c;border:1px solid var(--line);border-radius:99px;padding:3px 10px;color:var(--mut);white-space:nowrap}
.pill.live{color:#7dffb0;border-color:rgba(44,255,133,.4)}.pill.down{color:#ff8d7d;border-color:rgba(255,80,60,.4)}
.stat{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.chip{font-size:12px;padding:6px 11px;border-radius:99px;background:var(--card2);border:1px solid #2b2015;color:#d6cabd}
.chip b{color:var(--o2)}
#toast{position:fixed;bottom:18px;right:50%;transform:translateX(50%) translateY(20px);background:#1d1d24;border:1px solid var(--o2);color:var(--txt);border-radius:12px;padding:10px 16px;font-size:13px;font-weight:700;opacity:0;pointer-events:none;transition:opacity .25s,transform .25s;z-index:9;max-width:90vw;text-align:center;box-shadow:0 10px 30px -10px var(--glow)}
#toast.show{opacity:1;transform:translateX(50%) translateY(0)}
#toast.err{border-color:var(--red)}
.spin{display:inline-block;width:13px;height:13px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:sp .7s linear infinite;vertical-align:-2px}
@keyframes sp{to{transform:rotate(360deg)}}
.ver{text-align:center;color:var(--mut);font-size:10px;opacity:.6;margin-top:14px;letter-spacing:1px}
a.dom{color:var(--o2);font-size:12px;text-decoration:none;direction:ltr;unicode-bidi:embed}
</style></head><body><div class="topbar"></div><div class="wrap">
<div class="brand">
<svg class="logo" viewBox="0 0 64 64" aria-hidden="true"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffc15e"/><stop offset=".55" stop-color="#ff7a10"/><stop offset="1" stop-color="#ff3d00"/></linearGradient></defs><path d="M32 3 57 17.5v29L32 61 7 46.5v-29z" fill="#120a03" stroke="url(#g)" stroke-width="2.5" stroke-linejoin="round"/><path d="M36.5 12 20 35h10.5L27 52l17-24H33.2z" fill="url(#g)"/></svg>
<div><h1>مینی‌اپ سلف</h1><div class="sub" id="sub" style="margin:0">در حال اتصال…</div></div>
<span class="pill" id="runpill" style="margin-right:auto">…</span>
</div>
<div class="card"><div class="me"><div class="avatar" id="meava">؟</div>
<div><h2 id="mename">…</h2><div class="u" id="meuser"></div></div>
<span class="live off" id="melive"><i></i><b id="melivetx">…</b></span></div>
<div class="stat" id="chips"></div><div id="domrow" style="margin-top:8px"></div></div>
<div class="tabs">
<button data-t="home" class="on">🏠 خانه</button><button data-t="feats">🎛 قابلیت‌ها</button><button data-t="game">🐱 بازی</button><button data-t="bak">💾 بکاپ</button>
</div>
<div id="toast"></div>
<div id="t-home">
<div class="card"><h3>🤖 وضعیت سلف</h3><div id="status">…</div><div class="row" style="margin-top:10px">
<button id="b-run">🟢 روشن</button><button id="b-stop" class="danger">🔴 خاموش</button><button id="b-restart">🔄 ریستارت</button>
</div><div class="row" style="margin-top:7px"><button id="b-refresh" class="ghost">↻ به‌روزرسانی وضعیت</button></div>
<small>روشن/خاموش کردن سلف، ریستارت، وضعیت لحظه‌ای (رم، آپتایم، حلقه‌های بازی).</small></div>
<div class="card"><h3>⚡ اجرای سریع دستور</h3><input id="q-target" value="me" dir="ltr" placeholder="me یا @group یا آیدی چت">
<input id="q-text" placeholder="مثلاً .میویی یا .وضعیت چت">
<button id="b-send" class="on">ارسال به سلف 🚀</button><div id="q-msg" style="margin-top:6px"></div>
<small>دستورهای بازی (.میویی .ماهیگیری .یخچال .پیشی .خفاش .نجات) رو توی چت بازی بفرست. me = سیو مسج.</small></div>
</div>
<div id="t-feats" class="hidden"><div class="card"><h3>🎛 قابلیت‌ها <span class="pill" id="oncount"></span></h3><div class="grid" id="feats" style="margin-top:8px"></div>
<small>سبز = روشن. روی هر قابلیت بزن روشن/خاموش می‌شه و بلافاصله به سلف ارسال می‌شه. برای راهنمای کامل روی بات /panel بزن.</small></div></div>
<div id="t-game" class="hidden"><div class="card"><h3>🐱 بازی میویی</h3><input id="g-chat" value="me" dir="ltr" placeholder="آیدی/یوزرنیم چت بازی">
<div class="grid" id="games" style="margin-top:8px"></div><div id="g-msg" style="margin-top:6px"></div>
<small>هر دکمه، دستورش رو توی همون چت اجرا می‌کنه. وضعیت دقیق بازی‌های یه چت: <code>.وضعیت چت</code></small></div></div>
<div id="t-bak" class="hidden"><div class="card"><h3>💾 پشتیبان‌گیری / بازیابی</h3><div class="row">
<button id="b-dl">⬇️ دانلود بکاپ</button><button id="b-last">♻️ آخرین بکاپ سرور</button></div>
<textarea id="b-json" rows="4" dir="ltr" placeholder="JSON بکاپ رو اینجا بذار برای بازیابی دستی"></textarea>
<button id="b-up" class="on">♻️ بازیابی از همین متن</button><div id="b-msg" style="margin-top:6px"></div>
<small>بکاپ تنظیماته (بدون سشن). بکاپ کامل زیپ (با سشن) رو از داخل بات با /backup_full بگیر.</small></div></div>
<div class="ver">ERFAN · SELF · MINIAPP</div></div>
<script>
const tg=window.Telegram?.WebApp;tg?.expand();tg?.ready();
try{tg?.setHeaderColor?.("#07070a");tg?.setBackgroundColor?.("#07070a");}catch(e){}
const $=id=>document.getElementById(id);
let INIT=tg?.initData||"";
if(!INIT){$("sub").textContent="⚠️ مینی‌اپ رو از داخل بات تلگرام باز کن (دکمه‌ی 📱 مینی‌اپ).";toast("از داخل بات بازش کن 📱",true);}
let TOAST_T=null;
function toast(msg,isErr){const t=$("toast");t.textContent=msg;t.classList.toggle("err",!!isErr);t.classList.add("show");clearTimeout(TOAST_T);TOAST_T=setTimeout(()=>t.classList.remove("show"),2600);try{tg?.HapticFeedback?.notificationOccurred?.(isErr?"error":"success");}catch(e){}}
function busy(btn,on,txt){if(!btn)return;btn.classList.toggle("busy",!!on);if(on){btn.dataset.t=btn.innerHTML;btn.innerHTML="<span class='spin'></span> "+(txt||"صبر کن…");}else if(btn.dataset.t){btn.innerHTML=btn.dataset.t;}}
async function api(path,body){body=body||{};let r;try{r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.assign({initData:INIT},body))});}catch(e){throw new Error("اتصال به سرور برقرار نشد 🌐");}
let j=null;try{j=await r.json();}catch(e){throw new Error("پاسخ سرور نامعتبره ("+r.status+")");}
if(!r.ok||j.ok===false)throw new Error((j&&j.error)||("خطا "+r.status));return j;}
const GAMES=[[".میویی 🐱",".میویی"],[".ماهیگیری 🎣",".ماهیگیری"],[".یخچال 🧊",".یخچال"],[".پیشی 😺",".پیشی"],[".خفاش 🦇",".خفاش"],[".نجات 🐈",".نجات"],[".وضعیت چت 🩺",".وضعیت چت"],[".گزارش 📊",".گزارش"]];
function fmtU(s){s=+s||0;const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return (d?d+" روز ":"")+(h?h+" ساعت ":"")+m+" دقیقه";}
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
function render(d){
const me=d.me||null;
if(me&&(me.name||me.username||me.id)){$("meava").textContent=((me.name||me.username||"?").trim().charAt(0)||"؟");$("mename").textContent=me.name||"—";$("meuser").textContent=(me.username?"@"+me.username+" · ":"")+(me.id||"");}
else{$("meava").textContent="🔌";$("mename").textContent="اکانت وصل نیست";$("meuser").textContent="";}
$("sub").textContent=d.sub?("🎫 "+d.sub):(d.mode==="single"?"👤 تک‌سلف روی اکانت خودت":"هاب سلف");
const pill=$("runpill");pill.textContent=d.failed?"⚠️ کرش":(d.running?"🟢 روشن":"🔴 خاموش");pill.className="pill "+(d.running&&!d.failed?"live":"down");
const lv=$("melive");lv.classList.toggle("off",!(d.running&&!d.failed));$("melivetx").textContent=d.failed?"کرش":(d.running?"متصل":"خاموش");
let head=d.failed?"⚠️ <b>سلف کرش کرده</b> — ریستارت بزن":(d.running?"🟢 <b>سلف روشنه</b>":"🔴 <b>سلف خاموشه</b>");
if(d.running&&d.uptime)head+=" · ⏱ "+fmtU(d.uptime);
if(d.running&&d.ram)head+=" · 🧠 "+d.ram+"MB";
if(d.authorized===true)head+=" · 📡 ✅";else if(d.authorized===false)head+=" · 📡 ❌";
$("status").innerHTML=head;
const ch=$("chips");ch.innerHTML="";
const add=function(t){const s=document.createElement("span");s.className="chip";s.innerHTML=t;ch.appendChild(s);};
add("🎛 <b>"+d.on_count+"</b> از "+d.total+" روشن");
if(d.uptime)add("⏱ "+fmtU(d.uptime));
if(d.restarts)add("🔄 "+d.restarts+" ریستارت");
if(d.pending>0)add("⏳ "+d.pending+" در نوبت");
if(d.loops)Object.keys(d.loops).forEach(function(k){add("🔄 "+esc(k)+": "+d.loops[k]+" چت");});
$("domrow").innerHTML=d.domain?("🌐 <a class='dom' target='_blank' rel='noopener' href='https://"+esc(d.domain)+"'>"+esc(d.domain)+"</a>"):"";
$("oncount").textContent=d.on_count+" از "+d.total+" روشن";
const caps=(d.caps||{run_stop:true,restore_last:true});
$("b-run").style.display=caps.run_stop?"":"none";
$("b-stop").style.display=caps.run_stop?"":"none";
$("b-last").style.display=caps.restore_last?"":"none";
const box=$("feats");box.innerHTML="";(d.feats||[]).forEach(function(f){const el=document.createElement("div");el.className="f"+(f.on&&f.toggle?" on":"");el.title=f.desc||"";el.innerHTML="<span class='dot'></span><span>"+f.emoji+" "+esc(f.name)+"</span><b class='"+(f.on?"":"st-off")+"'>"+(f.toggle?(f.on?"روشن":"خاموش"):"دستوری")+"</b>";if(f.toggle){el.onclick=function(){return (async function(){el.classList.add("busy");try{const n=await api("/api/toggle",{key:f.key,value:!f.on});toast((!f.on?"روشن شد ✅ ":"خاموش شد ")+f.name);render(n);}catch(e){toast(e.message,true);}el.classList.remove("busy");})();};}else{el.onclick=function(){toast(f.desc||f.name);};}box.appendChild(el);});
}
async function load(btn){if(btn)busy(btn,true);try{const d=await api("/api/me");if(!d.connected){$("meava").textContent="🔌";$("mename").textContent="اکانت وصل نیست";$("meuser").textContent="";$("sub").textContent="🔌 "+(d.hint||"")+" · "+(d.sub||"");$("status").innerHTML="🔌 اکانت وصل نیست. توی بات /connect بزن.";$("chips").innerHTML="";return;}
render(d);}catch(e){$("sub").textContent="❌ "+e.message;toast(e.message,true);}if(btn)busy(btn,false);}
function buildGames(){const g=$("games");if(g.children.length)return;GAMES.forEach(function(gm){const t=gm[0],c=gm[1];const b=document.createElement("button");b.textContent=t;b.onclick=function(){return (async function(){busy(b,true);try{const chat=$("g-chat").value.trim()||"me";await api("/api/cmd",{target:chat,text:c});$("g-msg").innerHTML="<span class='ok'>✅ فرستاده شد به "+esc(chat)+"</span>";try{tg?.HapticFeedback?.impactOccurred?.("medium");}catch(e){}}catch(e){$("g-msg").innerHTML="<span class='err'>❌ "+esc(e.message)+"</span>";}busy(b,false);})();};g.appendChild(b);});}
document.querySelectorAll(".tabs button").forEach(function(b){b.onclick=function(){document.querySelectorAll(".tabs button").forEach(function(x){x.classList.remove("on");});b.classList.add("on");["home","feats","game","bak"].forEach(function(t){$("t-"+t).classList.toggle("hidden",t!==b.dataset.t);});if(b.dataset.t==="game")buildGames();try{tg?.HapticFeedback?.impactOccurred?.("light");}catch(e){}};});
$("b-run").onclick=function(e){return (async function(){const b=e.target.closest("button");busy(b,true);try{const d=await api("/api/control",{action:"run"});toast(d.msg||"🟢 داره روشن می‌شه");render(d);}catch(e){toast(e.message,true);}busy(b,false);})();};
$("b-stop").onclick=function(e){return (async function(){const b=e.target.closest("button");busy(b,true);try{const d=await api("/api/control",{action:"stop"});toast(d.msg||"🔴 خاموش شد");render(d);}catch(e){toast(e.message,true);}busy(b,false);})();};
$("b-restart").onclick=function(e){return (async function(){const b=e.target.closest("button");busy(b,true,"ریستارت…");try{const d=await api("/api/control",{action:"restart"});toast(d.msg||"🔄 داره ریستارت می‌شه");render(d);}catch(e){toast(e.message,true);}busy(b,false);})();};
$("b-refresh").onclick=function(e){load(e.target.closest("button"));};
$("b-send").onclick=function(){return (async function(){const b=$("b-send");busy(b,true,"ارسال…");try{const t=$("q-text").value.trim();if(!t)throw new Error("اول یه دستور بنویس (مثلاً .میویی)");const d=await api("/api/cmd",{target:$("q-target").value.trim()||"me",text:t});$("q-msg").innerHTML="<span class='ok'>"+esc(d.msg)+"</span>";}catch(e){$("q-msg").innerHTML="<span class='err'>❌ "+esc(e.message)+"</span>";}busy(b,false);})();};
$("b-dl").onclick=function(){return (async function(){const b=$("b-dl");busy(b,true);try{const d=await api("/api/backup");const blob=new Blob([JSON.stringify(d.backup,null,1)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="self-backup.json";document.body.appendChild(a);a.click();a.remove();toast("⬇️ بکاپ دانلود شد");}catch(e){toast(e.message,true);}busy(b,false);})();};
$("b-last").onclick=function(){return (async function(){const b=$("b-last");busy(b,true);try{const d=await api("/api/restore_last");$("b-msg").innerHTML="<span class='ok'>"+esc(d.msg)+"</span>";toast("♻️ برگردونده شد");render(d);}catch(e){$("b-msg").innerHTML="<span class='err'>❌ "+esc(e.message)+"</span>";}busy(b,false);})();};
$("b-up").onclick=function(){return (async function(){const b=$("b-up");busy(b,true);try{let obj;try{obj=JSON.parse($("b-json").value);}catch(e){throw new Error("متن JSON معتبر نیست");}const d=await api("/api/restore",{backup:obj});$("b-msg").innerHTML="<span class='ok'>"+esc(d.msg)+"</span>";toast("♻️ بازیابی شد");render(d);}catch(e){$("b-msg").innerHTML="<span class='err'>❌ "+esc(e.message)+"</span>";}busy(b,false);})();};
buildGames();load();
</script></body></html>"""
