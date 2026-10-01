# سلف تلگرام با ساعت — ورود از پنل وب

## دیپلوی روی Railway
1. پروژه رو توی یه ریپوی GitHub (private) بذار و توی Railway ← Deploy from GitHub.
2. **Variables**:
   - `PANEL_PASSWORD` ← یه رمز قوی برای پنل
   - `API_ID` و `API_HASH` ← **اختیاریه**؛ اگه نذاری، خود پنل ازت می‌پرسه (از my.telegram.org)
   - `TIMEZONE` = `Asia/Tehran` (اختیاری)
3. **Volume** بساز و Mount Path رو `/data` بذار (که بعد از ریدیپلوی دوباره لاگین نخوای).
4. Settings ← Networking ← **Generate Domain**.

## ورود
1. آدرس دامنه رو باز کن، رمز پنل رو بزن.
2. شماره تلگرامت رو با کد کشور بزن (+98...).
3. کدی که داخل تلگرام اومد رو بزن (اگه تایید دو مرحله‌ای داری، رمزش رو هم).
4. تموم! ساعت شروع به آپدیت می‌کنه. از همون پنل فونت/محل نمایش/خاموش‌کردن رو عوض کن.

## دستورات داخل تلگرام
`.clock on` / `.clock off` / `.clock name` / `.clock bio` / `.clock font 1-5` / `.ping` / `.help`
