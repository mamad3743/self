"""بروزرسانی سلف با فایل: زیپ پروژه یا چند فایل .py رو توی Saved Messages بفرست.

مراحل: دانلود ← فقط فایل‌های مجاز ← بررسی سینتکس ← تست import توی یه پردازش جدا ← اعمال ← ریستارت.
نسخه‌ی قبلی توی code.prev می‌مونه (.آپدیت برگشت).
"""
import os
import re
import sys
import json
import shutil
import asyncio
import zipfile
import tempfile
import hashlib

import core
import boot
from core import F, CFG, state, log

ALLOWED = set(boot.CODE_FILES)
MAX_FILE = 2_000_000
MAX_ZIP = 8_000_000
PREV = boot.CODE_DIR.rstrip("/") + ".prev"
_busy = asyncio.Lock()


def norm_name(name: str) -> str:
    """'features (1).py' ← 'features.py' (تلگرام موقع تکراری بودن عدد اضافه می‌کنه)."""
    base = os.path.basename((name or "").replace("\\", "/"))
    return re.sub(r"\s*\(\d+\)(\.py)$", r"\1", base)


def extract(path: str, filename: str) -> dict:
    """{نام: بایت} فقط برای فایل‌های مجاز؛ بقیه نادیده گرفته می‌شن (پوشه‌های داخل زیپ مهم نیستن)."""
    out, skipped = {}, []
    if filename.lower().endswith(".zip"):
        if os.path.getsize(path) > MAX_ZIP:
            raise ValueError("زیپ خیلی بزرگه")
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                n = norm_name(info.filename)
                if "__MACOSX" in info.filename or n.startswith("._"):
                    continue
                if n in ALLOWED:
                    if info.file_size > MAX_FILE:
                        raise ValueError(f"{n} خیلی بزرگه")
                    out[n] = z.read(info)
                elif n.endswith(".py") or n == "requirements.txt":
                    skipped.append(n)
    else:
        n = norm_name(filename)
        if n not in ALLOWED:
            raise ValueError(f"«{n}» جزو فایل‌های مجاز نیست. مجاز: {' '.join(sorted(ALLOWED))}")
        if os.path.getsize(path) > MAX_FILE:
            raise ValueError("فایل خیلی بزرگه")
        with open(path, "rb") as f:
            out[n] = f.read()
    return {"files": out, "skipped": skipped}


def syntax_check(files: dict):
    for n, data in files.items():
        if n.endswith(".py"):
            try:
                compile(data, n, "exec")
            except SyntaxError as e:
                raise ValueError(f"خطای سینتکس توی {n} خط {e.lineno}: {e.msg}")


async def smoke_test(stage: str):
    """نسخه‌ی جدید توی یه پردازش جدا import می‌شه تا خطای import/اسرت قبل از اعمال پیدا بشه."""
    env = dict(os.environ)
    env.update(SELF_OVERLAY="1", PYTHONDONTWRITEBYTECODE="1")
    env.setdefault("PANEL_PASSWORD", "test")
    env["PYTHONPATH"] = boot.REPO_DIR
    code = "import core, extras, botpanel, meow, features, updater, ctl, hub, railway, miniapp, main"
    p = await asyncio.create_subprocess_exec(
        sys.executable, "-c", code, cwd=stage, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), 60)
    except asyncio.TimeoutError:
        p.kill()
        raise ValueError("تست بالا اومدن نسخه‌ی جدید بیش از ۶۰ ثانیه طول کشید")
    if p.returncode != 0:
        tail = out.decode("utf-8", "ignore").strip().splitlines()[-3:]
        raise ValueError("نسخه‌ی جدید import نمی‌شه:\n" + "\n".join(tail)[-400:])


def current_files() -> dict:
    d = boot.CODE_DIR
    return {n: os.path.join(d, n) for n in sorted(os.listdir(d)) if n in ALLOWED} if os.path.isdir(d) else {}


def short_hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:8]


async def apply(path: str, filename: str, note=None):
    """مسیر فایل رو بررسی و اعمال می‌کنه؛ (True, پیام) یا (False, علت)."""
    if _busy.locked():
        return False, "یه بروزرسانی دیگه در حال انجامه"
    async with _busy:
        try:
            pack = extract(path, filename)
            files, skipped = pack["files"], pack["skipped"]
            if not files:
                return False, "توی فایل هیچ کد مجازی پیدا نشد (main/core/features/meow/botpanel/updater/boot/hub/railway)"
            syntax_check(files)
            stage = tempfile.mkdtemp(prefix="selfupd_")
            try:
                for n, p in current_files().items():  # روی نسخه‌ی بروزرسانی‌شده‌ی فعلی سوار می‌شه
                    shutil.copy(p, os.path.join(stage, n))
                for n, data in files.items():
                    with open(os.path.join(stage, n), "wb") as f:
                        f.write(data)
                await smoke_test(stage)
                changed = [n for n, d in files.items()
                           if not os.path.isfile(os.path.join(boot.REPO_DIR, n))
                           or open(os.path.join(boot.REPO_DIR, n), "rb").read() != d]
                os.makedirs(os.path.dirname(boot.CODE_DIR) or ".", exist_ok=True)
                shutil.rmtree(PREV, ignore_errors=True)
                if os.path.isdir(boot.CODE_DIR):
                    os.replace(boot.CODE_DIR, PREV)
                shutil.copytree(stage, boot.CODE_DIR)
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        except (ValueError, zipfile.BadZipFile) as e:
            return False, str(e)
        except Exception as e:  # noqa
            log.warning("update failed: %r", e)
            return False, f"{type(e).__name__}: {str(e)[:200]}"
        boot._write(boot.STATE, {"tries": 0, "base": boot.fingerprint(boot.REPO_DIR)})
        names = " ، ".join(sorted(files))
        msg = f"✅ بروزرسانی اعمال شد: {names}"
        if skipped:
            msg += f"\n(نادیده: {' '.join(skipped)})"
        if "requirements.txt" in skipped:
            msg += "\n⚠️ اگه کتابخونه‌ی جدید لازمه، باید از طریق GitHub دیپلوی کنی؛ از این راه نصب نمی‌شه."
        boot._write(boot.NOTE, {"msg": msg + "\n✅ ریستارت انجام شد"})
        return True, msg


def restore_prev() -> str:
    """برگشت به نسخه‌ی قبلی (یا اگه نسخه‌ی قبلی نبود، به کد GitHub)."""
    d = boot.CODE_DIR
    if os.path.isdir(PREV):
        shutil.rmtree(d, ignore_errors=True)
        os.replace(PREV, d)
        boot._write(boot.STATE, {"tries": 0, "base": boot.fingerprint(boot.REPO_DIR)})
        return "↩️ به نسخه‌ی قبلی برگشتم"
    return reset()


def reset() -> str:
    shutil.rmtree(boot.CODE_DIR, ignore_errors=True)
    shutil.rmtree(PREV, ignore_errors=True)
    try:
        os.remove(boot.STATE)
    except OSError:
        pass
    return "🧹 همه‌ی بروزرسانی‌ها پاک شد؛ نسخه‌ی GitHub اجرا می‌شه"


def status() -> str:
    cur = current_files()
    if not cur:
        return "📦 نسخه‌ی فعال: همون کد GitHub (بروزرسانی‌ای اعمال نشده)"
    rows = "\n".join(f"• {n} ({short_hash(p)})" for n, p in cur.items())
    prev = "هست ✅ (.آپدیت برگشت)" if os.path.isdir(PREV) else "نیست"
    return f"📦 فایل‌های بروزرسانی‌شده (روی کد GitHub اولویت دارن):\n{rows}\n\nنسخه‌ی قبلی: {prev}"


def restart():
    """پردازش رو با کد جدید دوباره اجرا می‌کنه (روی Railway کانتینر عوض نمی‌شه، پس Volume و پورت سر جاشون)."""
    try:
        sys.stdout.flush()
    except Exception:  # noqa
        pass
    os.environ.pop("SELF_OVERLAY", None)
    target = os.path.join(boot.REPO_DIR, "main.py")
    try:
        os.chdir(boot.REPO_DIR)
        os.execv(sys.executable, [sys.executable, target])
    except OSError as e:
        log.error("restart exec failed: %r", e)
        os._exit(1)  # Railway خودش دوباره بالا میاره


async def announce():
    """بعد از ریستارت: نتیجه‌ی بروزرسانی یا برگشت خودکار رو توی Saved Messages می‌گه."""
    try:
        with open(boot.NOTE) as f:
            note = json.load(f).get("msg")
        os.remove(boot.NOTE)
    except (OSError, ValueError):
        return
    if note:
        try:
            await core.client.send_message("me", note)
        except Exception as e:  # noqa
            log.warning("update note failed: %r", e)


async def mark_healthy():
    await asyncio.sleep(45)
    try:
        boot.healthy()
    except Exception:  # noqa
        pass
