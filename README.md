# CyberAI Pro — Phase 12

Flask-based Uzbek AI assistant with username/password authentication, chat history, AI modes, premium requests and administrator approval.

## Features
- Dedicated About page at `/about` describing the platform, features, plans, technology, and limitations.
- Image attachment in chat for PNG/JPG/WEBP up to 5 MB (requires an image-capable AI model).
- Matrix-inspired interface, responsive chat layout, side code-rain decorations, and SVG favicon.
- Local username/password accounts; passwords use Werkzeug password hashes. Google OAuth is not used.
- Unified AI assistant for general questions, programming help, and defensive cybersecurity learning.
- Context from the user's six latest conversations.
- Account-scoped history, search and clear-history actions.
- Typewriter display, scroll-follow pause when the user scrolls upward, jump-to-latest and stop-display controls.
- Fenced code blocks with a copy button.
- CSRF checks for POST/DELETE actions, basic in-process login-attempt throttling, security headers, HTTP-only session cookie.
- Manual premium approval by administrator.

## Install on Windows
1. Stop the current app and back up your project folder, `.env`, and `cyber.db`.
2. Extract the ZIP and copy project files over the existing `C:\CyberAI_Pro` folder. Keep your existing `.env` and `cyber.db`; this ZIP intentionally does not contain either file.
3. In Command Prompt:
   ```bat
   cd C:\CyberAI_Pro
   py -m pip install -r requirements.txt
   py app.py
   ```
4. Open `http://127.0.0.1:5000` and press Ctrl+F5.

## Environment configuration
Keep `.env` private. Required AI variables are `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`. `.env.example` documents the expected values. Use a long random `FLASK_SECRET_KEY`. On localhost keep `COOKIE_SECURE=0`; only set it to `1` when using HTTPS.

## Create the first administrator
Before the first start, set these values in `.env`:
```env
ADMIN_USERNAME=admin
ADMIN_PASSWORD=use-a-long-unique-password
ADMIN_EMAIL=admin@example.com
```
Restart the app. If the username already exists, startup promotes that account to administrator but does not change its password. Sign in using that account and open `/admin`. Remove or change the bootstrap credentials after setup. Do not share `.env`.

## Manual premium workflow
- User opens `/premium`, chooses one of the configured plans and submits a payment reference/note.
- Admin checks the payment outside the app, then approves or rejects the request in `/admin`.
- Approval activates the plan for its duration. No payment is processed automatically by this app. Never approve a request before verifying payment through your trusted payment channel.

Configured plans: 1 month — 15,000 UZS; 3 months — 40,000 UZS; 6 months — 70,000 UZS; 1 year — 100,000 UZS. Durations are currently treated as 30/90/180/365 days.

## Important limitations
- AI answers require a valid provider API key, model and quota. The AI request currently returns the provider response before the frontend typewriter animation begins; this is visual typing, not token-by-token provider streaming.
- Login throttling is in-memory and best suited to a single local process. For public deployment, use a persistent rate limiter, HTTPS, a persistent database and backups.
- Premium requests only record the payment note; payment itself is not verified by a gateway. Admin must manually verify the transaction.
- Always test with a backup of your real database before deployment.

## Pro obuna va administrator boshqaruvi

- Pro tariflar: 1 oy — 15 000 so‘m, 3 oy — 40 000 so‘m, 6 oy — 70 000 so‘m, 1 yil — 100 000 so‘m.
- Foydalanuvchi `/premium` sahifasida Telegram `@khayitboyeff` orqali to‘lov bo‘yicha murojaat qiladi va chek/tranzaksiya ma’lumotini so‘rovga kiritadi.
- Admin `/admin` sahifasida so‘rovni tasdiqlaydi/rad etadi. `/admin/users` sahifasida barcha foydalanuvchilarni qidirish va qo‘lda Pro obuna berish mumkin.
- Pro foydalanuvchi 10 000 belgigacha savol va 12 ta oldingi suhbat almashinuvini kontekst sifatida ishlatadi; bepul hisob 5 000 belgi va 4 ta oldingi almashinuv bilan cheklangan.
- Adminni sozlash uchun `.env` ichida `ADMIN_USERNAME`, `ADMIN_PASSWORD` va ixtiyoriy `ADMIN_EMAIL` belgilanadi. `.env` va `cyber.db` ni hech qachon begona joyga yubormang.
- To‘lovlar avtomatik tekshirilmaydi; administrator tranzaksiyani tashqi kanal orqali tekshirishi shart. Hech qachon karta PIN-kodi yoki SMS-kodni so‘ramang.



## Render deployment notes
- Upload the contents of this folder to the repository root (so `app.py`, `templates/`, and `static/` are at the same level).
- Render Build Command: `pip install -r requirements.txt`
- Render Start Command: `gunicorn --bind 0.0.0.0:$PORT app:app`
- Set `FLASK_SECRET_KEY` in Render Environment to a long random secret (at least 32 characters).
- Set `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` as needed.
- Do not upload `.env` or `cyber.db` to a public repository. Back up/migrate the database separately if it contains accounts or chat history.


## Qo‘shilgan funksiyalar
- Free/PRO kunlik AI limitlari: `DAILY_LIMIT_FREE` (standart 20) va `DAILY_LIMIT_PRO` (standart 200) environment variable orqali sozlanadi.
- Chat tarixini papkalarga ajratish: Umumiy, Kod, Kiberxavfsizlik, O‘qish, Loyiha.
- PRO so‘rovlariga reference ID, obuna holati va bildirishnomalar. To‘lov tasdiqlash hozircha admin orqali qo‘lda amalga oshadi.
- Admin statistikasi, foydalanuvchilarga e’lon yuborish, support/feedback murojaatlarini boshqarish.
- Yangi DB jadvallari va `history.folder` ustuni ilova ishga tushganda qo‘shiladi; mavjud yozuvlar saqlanadi.
