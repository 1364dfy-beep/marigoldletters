# راه‌اندازی آپلود خودکار روی تیک‌تاک

## این چطور کار می‌کند (و چرا «پست خودکار کامل» نیست)

هر روز workflow ویدیو را می‌سازد و به **Inbox تیک‌تاک خودت** به‌صورت **draft** می‌فرستد. تو یک اعلان می‌گیری، آن را باز می‌کنی،
(اختیاری) یک Sound ترند اضافه می‌کنی، گزینه‌ی AI را مطابق نیازت می‌زنی و **Post** را می‌زنی. حدود ۱ دقیقه در روز.

چرا Direct Post نه؟ چون تیک‌تاک تا وقتی اپ شما **audit** نشده، همه‌ی پست‌های Direct Post را فقط **خصوصی (SELF_ONLY)** می‌کند،
و رهنمودهای تیک‌تاک می‌گویند اپ نباید فقط برای استفاده‌ی داخلی/شخصی باشد؛ یعنی یک ربات شخصی عملاً audit نمی‌شود.
مسیر **inbox (draft)** پشت audit نیست و رایگان است. جزئیات فنی همین حالا در مستندات تیک‌تاک بررسی شد، ولی پورتال‌شان
مدام عوض می‌شود؛ اگر اسم دکمه‌ای فرق داشت، همان معادلش را پیدا کن.

## ۱) صفحات GitHub Pages (برای ثبت اپ)
تیک‌تاک موقع ثبت اپ آدرس‌های Redirect، Terms و Privacy می‌خواهد. پوشه‌ی `docs/` همین‌ها را دارد.

1. در GitHub: **Settings → Pages → Source: Deploy from a branch → Branch: main، Folder: /docs → Save**.
2. بعد از ~۱ دقیقه آدرس `https://USERNAME.github.io/REPO/` باز می‌شود. صفحات `terms.html` و `privacy.html` را هم چک کن.

> Pages در پلن رایگان فقط برای ریپوی **public** کار می‌کند. کلیدها در Secrets هستند و دیده نمی‌شوند؛ ولی اگر ریپو را private می‌خواهی،
> فقط پوشه‌ی `docs/` را در یک ریپوی public جدا بگذار و همان آدرس را استفاده کن.

## ۲) ساخت اپ در TikTok for Developers
1. به https://developers.tiktok.com برو و با همان اکانت تیک‌تاکی که می‌خواهی ویدیو رویش برود وارد شو.
2. **Manage apps → Connect an app** (نوع: Individual).
3. فیلدها: نام اپ (مثلاً Marigold Letters)، آیکون، دسته‌بندی، توضیح
   («Personal tool that uploads my own original videos as drafts to my TikTok inbox»)،
   **Terms URL** و **Privacy URL** از Pages، پلتفرم **Web** و Website URL = آدرس Pages.
4. **Add products:**
   - **Login Kit**: Redirect URI را دقیقاً برابر آدرس Pages بگذار (`https://USERNAME.github.io/REPO/` با همان اسلش آخر).
   - **Content Posting API**: فقط **Upload** لازم است (Direct Post را فعال نکن). اسکوپ‌ها: `user.info.basic` و `video.upload`.
5. **Sandbox:** یک Sandbox اضافه کن و اکانت تیک‌تاک خودت را به **Target Users** اضافه کن. (در Sandbox فقط همین کاربران می‌توانند وصل شوند،
   که برای ما کافی است.) `Client key` و `Client secret` را از همان Sandbox بردار.
6. در موبایل، اپ تیک‌تاک را آپدیت کن و با همان اکانت وارد باش.

## ۳) گرفتن Refresh Token (یک بار، روی کامپیوتر خودت)
```bash
pip install requests
export TIKTOK_CLIENT_KEY="..."
export TIKTOK_CLIENT_SECRET="..."
export TIKTOK_REDIRECT_URI="https://USERNAME.github.io/REPO/"

python tools/tiktok_auth.py url
#   لینک چاپ‌شده را در مرورگر باز کن، Authorize را بزن؛ به صفحه‌ی Pages برمی‌گردی که آدرس/کد را نشان می‌دهد.

python tools/tiktok_auth.py exchange "آدرس کامل صفحه‌ای که به آن ریدایرکت شدی"
#   خروجی: TIKTOK_REFRESH_TOKEN = rft....
```
(ویندوز: به‌جای `export` از `set` یا PowerShell با `$env:` استفاده کن.) کد چند دقیقه اعتبار دارد؛ اگر خطا گرفتی مرحله‌ی `url` را دوباره بزن.

## ۴) Secrets در GitHub
**Settings → Secrets and variables → Actions → New repository secret**

| نام | لازم؟ | توضیح |
|---|---|---|
| `TIKTOK_CLIENT_KEY` | بله | از Sandbox |
| `TIKTOK_CLIENT_SECRET` | بله | از Sandbox |
| `TIKTOK_REFRESH_TOKEN` | بله | از مرحله‌ی ۳ |
| `GH_PAT` | توصیه می‌شود | Fine-grained token: فقط همین ریپو، **Secrets: Read and write**. تیک‌تاک ممکن است در هر refresh توکن جدید بدهد؛ با این، workflow خودش آن را ذخیره می‌کند. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | توصیه می‌شود | API آپلود ویدیو کپشن نمی‌گیرد؛ با تلگرام کپشن آماده روی گوشی‌ات می‌آید. بات را از @BotFather بساز، به آن پیام بده، و `chat id` را از `https://api.telegram.org/bot<TOKEN>/getUpdates` بخوان. |

اگر Telegram نگذاری، کپشن در **خلاصه‌ی Run** (Actions) و فایل `ep_XXX.json` در Artifacts هست.

## ۵) اولین اجرا
**Actions → daily-episode → Run workflow.** در انتها باید خط `uploaded to TikTok inbox` را ببینی.
بعد در اپ تیک‌تاک: **Inbox → اعلان draft → ادیت → Post.**

## عیب‌یابی
| پیام | یعنی |
|---|---|
| `spam_risk_too_many_pending_share` | بیشتر از ۵ draft نهایی‌نشده در ۲۴ ساعت دارید. draftهای قدیمی را Post یا حذف کن. |
| `scope_not_authorized` / `token does not include video.upload` | مرحله‌ی ۳ را دوباره بزن و مطمئن شو Content Posting API به اپ اضافه شده. |
| `token refresh failed` | Refresh token منقضی (۳۶۵ روز) یا باطل شده؛ مرحله‌ی ۳ را تکرار کن و secret را عوض کن. |
| اعلان نمی‌آید | اکانت باید Target User باشد؛ اپ تیک‌تاک را آپدیت کن؛ چند دقیقه صبر کن (وضعیت `SEND_TO_USER_INBOX` یعنی تیک‌تاک اعلان را فرستاده). |
| `::warning:: ... NEW refresh token` | `GH_PAT` نیست و توکن جدید ذخیره نشد؛ GH_PAT را اضافه کن یا مرحله‌ی ۳ را تکرار کن. |

## چیزهایی که مطمئن نیستم (اولین اجرا روشن می‌کند)
- **منتشر شدن عمومی پست در حالت Sandbox:** چون پست را خودت در اپ تیک‌تاک نهایی می‌کنی باید مشکلی نباشد، ولی من آن را اجرا نکرده‌ام.
- اگر روزی تیک‌تاک برای ادامه‌ی کار **App review** خواست، یک اپ شخصی ممکن است رد شود؛ در آن صورت همان مسیر Sandbox را نگه دار.
- مسیر رمزنگاری ذخیره‌ی `GH_PAT` (PyNaCl) را اینجا نتوانستم اجرا کنم؛ طبق روش رسمی GitHub نوشته شده. اگر اولین بار خطا داد، لاگ را بفرست.
