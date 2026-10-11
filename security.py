#!/usr/bin/env python3
"""CyberAI Pro uchun xavfsiz, passiv 30 bandli konfiguratsiya auditi.

Ishlatish: python security.py [project_path] [--url http://127.0.0.1:5000]
Ushbu skript zararli payload yubormaydi va tizimga hujum qilmaydi; manba kodi
va ixtiyoriy ravishda oddiy HTTP sarlavhalarini tekshiradi. Natija to'liq pentest emas.
"""
from __future__ import annotations
import argparse, ast, re, sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

CHECKS = [
("Login parol tekshiruvi", lambda c: "check_password_hash" in c),
("3 urinishdan keyin hisob bloklash", lambda c: "count >= 3" in c and "locked_until" in c),
("IP manzil login logida saqlanishi", lambda c: "security_login_log" in c and "ip_address" in c),
("Brute-force hisob himoyasi", lambda c: "failed_count" in c and "locked_until" in c),
("Login rate-limit mexanizmi", lambda c: "locked_until" in c and "failed_count" in c),
("Ro'yxatdan o'tish parol minimumi", lambda c: bool(re.search(r'len\(password\)\s*<\s*8', c))),
("Parol hash ishlatilishi", lambda c: "generate_password_hash" in c and "check_password_hash" in c),
("Sessiya login vaqtida yangilanishi", lambda c: 'session.clear()' in c and 'session["user_id"]' in c),
("HttpOnly cookie", lambda c: "SESSION_COOKIE_HTTPONLY=True" in c),
("SameSite cookie", lambda c: 'SESSION_COOKIE_SAMESITE="Lax"' in c),
("CSRF tekshiruvi", lambda c: "protect_state_changes" in c and "compare_digest" in c),
("XSS uchun JS escaping", lambda c: "function esc" in (ROOT/'static/chat.js').read_text(encoding='utf-8',errors='ignore')),
("SQL parametrli so'rovlar", lambda c: "WHERE username=?" in c and "(username,)" in c),
("Admin server-side authorization", lambda c: "def admin_required" in c and "abort(403)" in c),
("Login bo'lmasa auth talab qilinishi", lambda c: "def login_required" in c),
("Yuklama hajmi limiti", lambda c: "MAX_CONTENT_LENGTH" in c),
("Rasm format allowlist", lambda c: "image/(?:png|jpeg|webp)" in c),
("Maxfiy kalit .env/env orqali", lambda c: "FLASK_SECRET_KEY" in c),
("Xato sahifada debug default o'chiq", lambda c: "debug=False" in c),
("AI API timeout", lambda c: "timeout=60" in c),
("AI endpoint so'rov hajmi tekshiruvi", lambda c: "max_question" in c and "len(question)" in c),
("HTTP xavfsizlik sarlavhalari", lambda c: "X-Content-Type-Options" in c and "X-Frame-Options" in c),
("HTTPS Secure cookie sozlamasi mavjud", lambda c: "SESSION_COOKIE_SECURE" in c),
("HSTS sozlamasi ko'rib chiqilishi kerak", lambda c: "Strict-Transport-Security" in c),
("Parolni tiklash funksiyasi olib tashlangan", lambda c: "/forgot-password" not in c and "/reset-password" not in c),
("Login urinishlari loglanadi", lambda c: "security_login_log" in c and '"failed"' in c),
("DB user foreign key / so'rovlar", lambda c: "sqlite3.connect(DB_PATH)" in c and "?" in c),
("API auth himoyasi", lambda c: "@login_required\ndef ask" in c or "@login_required\n@app.route(\"/ask\"" in c),
("Production WSGI dependency", lambda c: "gunicorn" in (ROOT/'requirements.txt').read_text(encoding='utf-8',errors='ignore').lower()),
("DB yoki .env audit ZIPga qo'shilmagan", lambda c: not (ROOT/'.env').exists() and not (ROOT/'cyber.db').exists()),
]
ROOT = Path(__file__).resolve().parent

def main():
    global ROOT
    ap=argparse.ArgumentParser(description="CyberAI Pro passiv xavfsizlik auditi (30 band)")
    ap.add_argument("project_path", nargs="?", default=str(ROOT), help="Loyiha papkasi")
    ap.add_argument("--url", help="Ixtiyoriy: o'zingiz boshqaradigan lokal/staging URL, masalan http://127.0.0.1:5000")
    args=ap.parse_args(); ROOT=Path(args.project_path).resolve()
    app_path=ROOT/'app.py'
    if not app_path.is_file(): print(f"XATO: app.py topilmadi: {app_path}"); return 2
    code=app_path.read_text(encoding='utf-8',errors='replace')
    try: ast.parse(code)
    except SyntaxError as e: print(f"XATO: app.py sintaksisi: {e}"); return 2
    print(f"CyberAI Pro Security Audit — {ROOT}\n")
    passed=warn=0
    for i,(name,fn) in enumerate(CHECKS,1):
        try: ok=bool(fn(code))
        except Exception: ok=False
        print(f"{i:02d}. {'PASS' if ok else 'WARN'} — {name}")
        passed += int(ok); warn += int(not ok)
    if args.url:
        print("\nHTTP sarlavhalari:")
        try:
            req=Request(args.url, headers={"User-Agent":"CyberAI-Pro-Local-Security-Audit/1.0"})
            try:
                with urlopen(req,timeout=5) as r: headers=r.headers; status=r.status
            except HTTPError as e: headers=e.headers; status=e.code
            print(f"HTTP javobi: {status}")
            for h in ("X-Content-Type-Options","X-Frame-Options","Referrer-Policy","Content-Security-Policy","Strict-Transport-Security"):
                print(f"{'PASS' if h in headers else 'WARN'} — {h}: {headers.get(h,'topilmadi')}")
        except (URLError,TimeoutError,OSError) as e: print(f"WARN — URL ulanilmadi: {e}")
    print(f"\nNatija: {passed}/{len(CHECKS)} band PASS, {warn} band WARN.")
    print("Eslatma: bu statik, passiv tekshiruv. PASS xavfsizlik kafolati emas; WARN hamisha zaiflik isboti emas.")
    return 0
if __name__=='__main__': raise SystemExit(main())
