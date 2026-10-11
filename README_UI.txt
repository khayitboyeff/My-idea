CyberAI Pro — Matrix Green UI update
=====================================
- Portfolio landing page with sections for project overview/features/security.
- Top "Kirish" button scrolls to login/register section.
- Login and registration use existing Flask routes /login and /register.
- Chat workspace has left conversation history, profile/logout at bottom, collapsible sidebar.
- Green Matrix code-rain background is used on landing and chat.
- Existing app.py, AI endpoint, database logic and requirements are retained.

Install:
1. Stop server with Ctrl+C.
2. Back up your existing project folder.
3. Copy these project files over the matching files in C:\CyberAI_Pro.
4. Keep your local .env file; it is intentionally not included in this ZIP.
5. Run: python app.py
6. Refresh browser with Ctrl+F5.

Note: UI files were checked for basic syntax and template route names. Test login, registration, chat and mobile sidebar after installing.

STANDALONE AUTH + GOOGLE SIGN-IN
- Kirish/ro'yxatdan o'tish endi alohida /auth sahifasida.
- Google OAuth ishlashi uchun .env ichiga GOOGLE_CLIENT_ID va GOOGLE_CLIENT_SECRET qo'shing.
- Google Cloud Console -> APIs & Services -> OAuth consent screen sozlang.
- Credentials -> Create Credentials -> OAuth client ID -> Web application yarating.
- Authorized redirect URI: http://127.0.0.1:5000/auth/google/callback
- Agar localhost bilan ochsangiz, qo'shimcha URI: http://localhost:5000/auth/google/callback
- So'ng pip install -r requirements.txt va serverni qayta ishga tushiring.
- Deploy qilinganda redirect URI ni production HTTPS domeningizga moslang.
- .env faylini hech qachon ZIP yoki Git orqali tarqatmang.
