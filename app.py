import os, sqlite3, urllib.request, json, secrets, time, base64, re, hashlib
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, session, jsonify, flash, url_for, abort, Response, stream_with_context
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "cyber.db"
app = Flask(__name__)
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

# Production must use a stable secret from the environment; do not silently rotate it on restart.
_is_production = os.environ.get("FLASK_ENV", "").lower() == "production" or os.environ.get("RENDER", "").lower() == "true"
_secret_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
if _is_production and len(_secret_key) < 32:
    raise RuntimeError("Production uchun .env/server environment ichida kamida 32 belgili FLASK_SECRET_KEY belgilang.")
if _secret_key:
    app.secret_key = _secret_key
elif _is_production:
    raise RuntimeError("Production muhitida FLASK_SECRET_KEY majburiy.")
else:
    # Local development: secret key restartlar orasida o'zgarmasligi uchun faylda saqlanadi.
    _secret_file = BASE_DIR / ".flask_secret_key"
    try:
        _secret_key = _secret_file.read_text(encoding="utf-8").strip()
        if len(_secret_key) < 32:
            raise ValueError("secret key file invalid")
    except (OSError, ValueError):
        _secret_key = secrets.token_hex(32)
        _secret_file.write_text(_secret_key, encoding="utf-8")
    app.secret_key = _secret_key
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(os.environ.get("COOKIE_SECURE", "").lower() in ("1", "true", "yes") or _is_production),
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)
# Redis is recommended in production so limits are shared between workers/instances.
# Configure RATELIMIT_STORAGE_URI=redis://... on the hosting provider.
_rate_storage = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["120 per minute", "2000 per hour"],
    storage_uri=_rate_storage,
    headers_enabled=True,
)

PLANS = {
    "monthly": {"name": "1 oy", "price": 15000, "days": 30},
    "quarterly": {"name": "3 oy", "price": 40000, "days": 90},
    "halfyear": {"name": "6 oy", "price": 70000, "days": 180},
    "yearly": {"name": "1 yil", "price": 100000, "days": 365},
}
_LOGIN_ATTEMPTS = {}
DAILY_LIMIT_FREE = int(os.environ.get("DAILY_LIMIT_FREE", "20"))
DAILY_LIMIT_PRO = int(os.environ.get("DAILY_LIMIT_PRO", "200"))
HISTORY_FOLDERS = ("Umumiy", "Kod", "Kiberxavfsizlik", "O‘qish", "Loyiha")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            google_id TEXT UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "google_id" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN google_id TEXT")
        if "is_admin" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        if "premium_until" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN premium_until TEXT")
        # Telegram recovery fields are added safely to existing databases.
        if "telegram_chat_id" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN telegram_chat_id TEXT")
        if "telegram_link_code_hash" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN telegram_link_code_hash TEXT")
        if "telegram_link_expires" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN telegram_link_expires INTEGER")
        conn.execute("""CREATE TABLE IF NOT EXISTS history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS premium_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            plan_key TEXT NOT NULL,
            payment_note TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT,
            reviewed_by INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )""")
        # Feature migrations are additive so existing accounts and history remain intact.
        history_cols = {row["name"] for row in conn.execute("PRAGMA table_info(history)").fetchall()}
        if "folder" not in history_cols:
            conn.execute("ALTER TABLE history ADD COLUMN folder TEXT NOT NULL DEFAULT 'Umumiy'")
        # Suhbatlar (threadlar): eski yozuvlarning har biri o'zining alohida suhbati bo'lib qoladi.
        if "thread_id" not in history_cols:
            conn.execute("ALTER TABLE history ADD COLUMN thread_id INTEGER")
        conn.execute("UPDATE history SET thread_id=id WHERE thread_id IS NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_history_user_thread ON history(user_id, thread_id)")
        premium_cols = {row["name"] for row in conn.execute("PRAGMA table_info(premium_requests)").fetchall()}
        if "reference_code" not in premium_cols:
            conn.execute("ALTER TABLE premium_requests ADD COLUMN reference_code TEXT")
        conn.execute("""CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, title TEXT NOT NULL,
            body TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'info', is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, category TEXT NOT NULL,
            subject TEXT NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
            admin_reply TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id))""")
    # Optional first admin: set ADMIN_USERNAME and ADMIN_PASSWORD in .env before starting.
    admin_name = os.environ.get("ADMIN_USERNAME", "").strip()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if admin_name and admin_password:
        with db() as conn:
            row = conn.execute("SELECT id FROM users WHERE username=?", (admin_name,)).fetchone()
            if row:
                conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (row["id"],))
            else:
                admin_email = (os.environ.get("ADMIN_EMAIL") or f"{admin_name}@localhost.invalid").strip().lower()
                try:
                    conn.execute("INSERT INTO users(username,email,password_hash,is_admin) VALUES(?,?,?,1)",
                                 (admin_name, admin_email, generate_password_hash(admin_password)))
                except sqlite3.IntegrityError:
                    app.logger.error("Admin bootstrap skipped: username/email already exists; set ADMIN_USERNAME to an existing account.")

def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]

app.jinja_env.globals["csrf_token"] = csrf_token


def telegram_api(method, payload):
    """Call Telegram Bot API without logging the bot token or payload secrets."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN sozlanmagan")
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Telegram API so‘rovni rad etdi")
    return result.get("result")


def send_telegram_message(chat_id, text):
    return telegram_api("sendMessage", {"chat_id": chat_id, "text": text})


def _sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@app.before_request
def protect_state_changes():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not supplied or not secrets.compare_digest(str(supplied), str(expected)):
            if request.is_json or request.path.startswith("/api/") or request.path == "/ask":
                return jsonify(error="Xavfsizlik tokeni eskirgan. Sahifani yangilang."), 400
            abort(400, description="Xavfsizlik tokeni eskirgan. Sahifani yangilang.")

@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.endpoint in ("chat", "profile", "premium", "admin_panel", "admin_users", "notifications_page", "support_page", "admin_feedback"):
        response.headers["Cache-Control"] = "no-store"
    return response

def create_notification(user_id, title, body, kind="info"):
    with db() as conn:
        conn.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,?)",
                     (user_id, str(title)[:120], str(body)[:1200], kind))

def _guess_history_folder(question):
    q = (question or "").lower()
    if any(k in q for k in ("python", "javascript", "kod", "bug", "error", "xato", "html", "css", "sql")):
        return "Kod"
    if any(k in q for k in ("xavfsizlik", "cyber", "phishing", "tarmoq", "firewall", "pentest")):
        return "Kiberxavfsizlik"
    if any(k in q for k in ("dars", "o‘rgan", "test", "kurs", "mashq")):
        return "O‘qish"
    if any(k in q for k in ("loyiha", "render", "github", "deploy", "sayt")):
        return "Loyiha"
    return "Umumiy"

def usage_for(user_id, premium_active):
    with db() as conn:
        used = conn.execute("SELECT COUNT(*) FROM history WHERE user_id=? AND date(created_at)=date('now')",
                            (user_id,)).fetchone()[0]
    limit = DAILY_LIMIT_PRO if premium_active else DAILY_LIMIT_FREE
    return {"used": used, "limit": limit, "remaining": max(0, limit-used), "premium": premium_active}

def current_user():
    if "user_id" not in session:
        return None
    with db() as conn:
        return conn.execute("SELECT id, username, email, is_admin, premium_until FROM users WHERE id=?", (session["user_id"],)).fetchone()

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("auth_page"))
        if not user["is_admin"]:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("home"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/")
def home():
    if current_user():
        return redirect(url_for("chat"))
    return redirect(url_for("auth_page"))

@app.route("/about")
def about_page():
    return render_template("about.html", user=current_user())


@app.route("/auth")
def auth_page():
    if current_user():
        return redirect(url_for("chat"))
    tab = "register" if request.args.get("tab") == "register" else "login"
    return render_template("auth.html", active_tab=tab)

@app.route("/register", methods=["POST"])
@limiter.limit("5 per hour")
def register():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if len(username) < 3 or len(username) > 32:
        flash("Username 3–32 belgidan iborat bo‘lsin.", "error")
        return redirect(url_for("auth_page", tab="register"))
    if len(password) < 8:
        flash("Parol kamida 8 ta belgidan iborat bo‘lishi kerak.", "error")
        return redirect(url_for("auth_page", tab="register"))
    try:
        with db() as conn:
            cur = conn.execute("INSERT INTO users(username,email,password_hash) VALUES(?,?,?)",
                               (username, email, generate_password_hash(password)))
            new_user_id = cur.lastrowid
        # Ro‘yxatdan o‘tgan foydalanuvchini avtomatik kiritamiz va chatga yo‘naltiramiz.
        session.clear()
        session["user_id"] = new_user_id
        session.permanent = True
        session["csrf_token"] = secrets.token_urlsafe(32)
        flash("Hisobingiz yaratildi. CyberAI Pro chatiga xush kelibsiz!", "success")
    except sqlite3.IntegrityError:
        flash("Bu username yoki email allaqachon ro‘yxatdan o‘tgan.", "error")
        return redirect(url_for("auth_page", tab="register"))
    return redirect(url_for("chat"))

@app.route("/login", methods=["POST"])
@limiter.limit("5 per minute; 20 per hour")
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    client = request.remote_addr or "unknown"
    now = time.time()
    attempts = [stamp for stamp in _LOGIN_ATTEMPTS.get(client, []) if now - stamp < 300]
    if len(attempts) >= 10:
        flash("Juda ko‘p urinish. 5 daqiqadan keyin qayta urinib ko‘ring.", "error")
        return redirect(url_for("auth_page"))
    with db() as conn:
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        attempts.append(now)
        _LOGIN_ATTEMPTS[client] = attempts
        flash("Username yoki parol noto‘g‘ri.", "error")
        return redirect(url_for("auth_page"))
    _LOGIN_ATTEMPTS.pop(client, None)
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True
    session["csrf_token"] = secrets.token_urlsafe(32)
    return redirect(url_for("chat"))



@app.route("/telegram-link", methods=["GET", "POST"])
@login_required
def telegram_link():
    # Old bookmarks are redirected to the new account center.
    return redirect(url_for("profile"))


@app.route("/profile", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute", methods=["POST"])
def profile():
    user = current_user()
    if request.method == "POST":
        action = request.form.get("action", "profile")
        if action == "profile":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            if len(username) < 3 or len(username) > 32:
                flash("Username 3–32 belgidan iborat bo‘lishi kerak.", "error")
                return redirect(url_for("profile"))
            if not email or len(email) > 254 or "@" not in email:
                flash("To‘g‘ri email manzilini kiriting.", "error")
                return redirect(url_for("profile"))
            try:
                with db() as conn:
                    conn.execute("UPDATE users SET username=?, email=? WHERE id=?",
                                 (username, email, user["id"]))
                flash("Profil ma’lumotlari yangilandi.", "success")
            except sqlite3.IntegrityError:
                flash("Bu username yoki email boshqa hisobda ishlatilmoqda.", "error")
            return redirect(url_for("profile"))

        if action == "password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            with db() as conn:
                row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
                if not row or not check_password_hash(row["password_hash"], current_password):
                    flash("Joriy parol noto‘g‘ri.", "error")
                elif len(new_password) < 8:
                    flash("Yangi parol kamida 8 ta belgidan iborat bo‘lsin.", "error")
                elif new_password != confirm_password:
                    flash("Yangi parollar bir-biriga mos kelmadi.", "error")
                else:
                    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                                 (generate_password_hash(new_password), user["id"]))
                    flash("Parol muvaffaqiyatli yangilandi.", "success")
            return redirect(url_for("profile"))
        abort(400)

    with db() as conn:
        details = conn.execute(
            "SELECT id, username, email, created_at, premium_until, is_admin FROM users WHERE id=?",
            (user["id"],)
        ).fetchone()
        chat_count = conn.execute("SELECT COUNT(*) FROM history WHERE user_id=?", (user["id"],)).fetchone()[0]
        request_count = conn.execute("SELECT COUNT(*) FROM premium_requests WHERE user_id=?", (user["id"],)).fetchone()[0]
    now_text = time.strftime("%Y-%m-%d %H:%M:%S")
    premium_active = bool(details["premium_until"] and details["premium_until"] > now_text)
    return render_template("profile.html", user=details, chat_count=chat_count,
                           request_count=request_count, premium_active=premium_active,
                           now_text=now_text)

@app.route("/chat")
@login_required
def chat():
    user = current_user()
    with db() as conn:
        rows = conn.execute("SELECT id,question,answer,created_at,folder FROM history WHERE user_id=? ORDER BY id DESC LIMIT 30",
                            (user["id"],)).fetchall()
        unread_count = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user["id"],)).fetchone()[0]
        thread_count = conn.execute("SELECT COUNT(DISTINCT thread_id) FROM history WHERE user_id=?", (user["id"],)).fetchone()[0]
    premium_active = bool(user["premium_until"] and str(user["premium_until"]) > time.strftime("%Y-%m-%d %H:%M:%S"))
    usage = usage_for(user["id"], premium_active)
    return render_template("chat.html", thread_count=thread_count, user=user, history=list(reversed(rows)), now_text=time.strftime("%Y-%m-%d %H:%M:%S"), usage=usage, folders=HISTORY_FOLDERS, unread_count=unread_count)

@app.route("/api/history")
@login_required
def api_history():
    user = current_user()
    with db() as conn:
        rows = conn.execute("SELECT id,question,answer,created_at,folder FROM history WHERE user_id=? ORDER BY id DESC LIMIT 30",
                            (user["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/history/export")
@login_required
def export_history():
    """Download only the signed-in user's conversation history as a UTF-8 text file."""
    user = current_user()
    with db() as conn:
        rows = conn.execute(
            "SELECT question, answer, created_at FROM history WHERE user_id=? ORDER BY id ASC",
            (user["id"],)
        ).fetchall()
    parts = [f"CyberAI Pro — Suhbatlar tarixi\nFoydalanuvchi: {user['username']}\n"]
    for index, row in enumerate(rows, 1):
        parts.append(
            f"\n{'=' * 60}\n#{index} · {row['created_at'] or 'Sana ko‘rsatilmagan'}\n"
            f"\nSAVOL:\n{row['question'] or ''}\n\nJAVOB:\n{row['answer'] or ''}\n"
        )
    content = "\n".join(parts)
    filename = f"cyberai_pro_history_{time.strftime('%Y%m%d')}.txt"
    return Response(
        content, mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                 "X-Content-Type-Options": "nosniff"}
    )


@app.route("/api/history/search")
@login_required
def search_history():
    user = current_user()
    q = request.args.get("q", "").strip()[:120]
    with db() as conn:
        if q:
            rows = conn.execute(
                "SELECT id,question,answer,created_at,folder FROM history WHERE user_id=? AND (question LIKE ? OR answer LIKE ?) ORDER BY id DESC LIMIT 50",
                (user["id"], f"%{q}%", f"%{q}%")
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,question,answer,created_at,folder FROM history WHERE user_id=? ORDER BY id DESC LIMIT 50",
                (user["id"],)
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/history/<int:item_id>/folder", methods=["POST"])
@login_required
def move_history_folder(item_id):
    user = current_user()
    data = request.get_json(silent=True) or {}
    folder = str(data.get("folder", "")).strip()
    if folder not in HISTORY_FOLDERS:
        return jsonify(error="Papka nomi noto‘g‘ri."), 400
    with db() as conn:
        cur = conn.execute("UPDATE history SET folder=? WHERE id=? AND user_id=?", (folder, item_id, user["id"]))
    if not cur.rowcount:
        return jsonify(error="Suhbat topilmadi."), 404
    return jsonify(ok=True, folder=folder)


@app.route("/api/history/<int:item_id>", methods=["DELETE"])
@login_required
def delete_history_item(item_id):
    user = current_user()
    with db() as conn:
        cur = conn.execute("DELETE FROM history WHERE id=? AND user_id=?", (item_id, user["id"]))
    if not cur.rowcount:
        return jsonify(error="Suhbat topilmadi."), 404
    return jsonify(ok=True)


@app.route("/api/history/clear", methods=["POST"])
@login_required
def clear_history():
    user = current_user()
    with db() as conn:
        conn.execute("DELETE FROM history WHERE user_id=?", (user["id"],))
    return jsonify(ok=True)



# ---------------------------------------------------------------- Suhbatlar (threadlar)
def _list_threads(user_id, q=""):
    with db() as conn:
        extra, params = "", [user_id]
        if q:
            tids = [r[0] for r in conn.execute(
                "SELECT DISTINCT thread_id FROM history WHERE user_id=? AND (question LIKE ? OR answer LIKE ?)",
                (user_id, f"%{q}%", f"%{q}%")).fetchall()]
            if not tids:
                return []
            extra = " AND thread_id IN (%s)" % ",".join("?" * len(tids))
            params += tids
        rows = conn.execute(
            "SELECT thread_id, MIN(id) AS first_id, MAX(id) AS last_id, COUNT(*) AS n FROM history "
            "WHERE user_id=?" + extra + " GROUP BY thread_id ORDER BY last_id DESC LIMIT 60", params).fetchall()
        out = []
        for r in rows:
            first = conn.execute("SELECT question, folder FROM history WHERE id=?", (r["first_id"],)).fetchone()
            last = conn.execute("SELECT created_at FROM history WHERE id=?", (r["last_id"],)).fetchone()
            title = (first["question"] or "").replace("[Rasm] ", "", 1).strip()[:90] or "Suhbat"
            out.append({"id": r["thread_id"], "title": title, "folder": first["folder"] or "Umumiy",
                        "created_at": last["created_at"], "count": r["n"]})
    return out


@app.route("/api/threads")
@login_required
def api_threads():
    user = current_user()
    q = request.args.get("q", "").strip()[:120]
    return jsonify(_list_threads(user["id"], q))


@app.route("/api/threads/<int:thread_id>")
@login_required
def api_thread_detail(thread_id):
    user = current_user()
    with db() as conn:
        rows = conn.execute(
            "SELECT id, question, answer, created_at, folder FROM history WHERE user_id=? AND thread_id=? ORDER BY id ASC",
            (user["id"], thread_id)).fetchall()
    if not rows:
        return jsonify(error="Suhbat topilmadi."), 404
    return jsonify(id=thread_id, folder=rows[0]["folder"], messages=[dict(r) for r in rows])


@app.route("/api/threads/<int:thread_id>", methods=["DELETE"])
@login_required
def api_thread_delete(thread_id):
    user = current_user()
    with db() as conn:
        cur = conn.execute("DELETE FROM history WHERE user_id=? AND thread_id=?", (user["id"], thread_id))
    if not cur.rowcount:
        return jsonify(error="Suhbat topilmadi."), 404
    return jsonify(ok=True)


@app.route("/api/threads/<int:thread_id>/folder", methods=["POST"])
@login_required
def api_thread_folder(thread_id):
    user = current_user()
    folder = str((request.get_json(silent=True) or {}).get("folder", "")).strip()
    if folder not in HISTORY_FOLDERS:
        return jsonify(error="Papka nomi noto‘g‘ri."), 400
    with db() as conn:
        cur = conn.execute("UPDATE history SET folder=? WHERE user_id=? AND thread_id=?", (folder, user["id"], thread_id))
    if not cur.rowcount:
        return jsonify(error="Suhbat topilmadi."), 404
    return jsonify(ok=True, folder=folder)


def _provider_http_message(code):
    if code == 401:
        return "API kaliti noto‘g‘ri yoki yaroqsiz. Kalitni tekshiring."
    if code == 403:
        return "API uchun ruxsat yo‘q. Kalit, loyiha yoki hududiy cheklovni tekshiring."
    if code == 404:
        return "Model yoki API manzili topilmadi. Terminaldagi AI provider HTTP error tafsilotini tekshiring."
    if code == 429:
        return "API kvotasi yoki so‘rov limiti tugagan."
    return f"AI provayderi HTTP {code} xatosini qaytardi. Terminalni tekshiring."


def _sse(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def _ask_stream(req, user, premium_active, question, image_url, thread_id):
    """Provayder javobini bo'lak-bo'lak (SSE) brauzerga uzatadi va oxirida tarixga saqlaydi."""
    import urllib.error
    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8", errors="replace")[:1500]
        app.logger.error("AI provider HTTP error: status=%s, details=%s", e.code, details)
        return jsonify(error=_provider_http_message(e.code)), 502
    except urllib.error.URLError as e:
        app.logger.error("AI provider connection error: %s", str(e.reason))
        return jsonify(error="AI serveriga ulanib bo‘lmadi. Internet va API manzilini tekshiring."), 502
    except Exception:
        app.logger.exception("Unexpected AI provider error")
        return jsonify(error="AI xizmatida kutilmagan xato. Terminal loglarini tekshiring."), 502

    user_id = user["id"]
    with db() as conn:
        if thread_id is None:
            thread_id = conn.execute("SELECT COALESCE(MAX(thread_id),0)+1 FROM history").fetchone()[0]
            folder = _guess_history_folder(question)
        else:
            row = conn.execute("SELECT folder FROM history WHERE user_id=? AND thread_id=? ORDER BY id ASC LIMIT 1",
                               (user_id, thread_id)).fetchone()
            folder = row["folder"] if row else _guess_history_folder(question)
    stored_question = ("[Rasm] " if image_url else "") + question

    def save(text):
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO history(user_id, question, answer, folder, thread_id) VALUES(?,?,?,?,?)",
                (user_id, stored_question, text, folder, thread_id))
            return cur.lastrowid

    def generate():
        parts, saved = [], False
        try:
            yield _sse({"start": True, "thread_id": thread_id})
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except ValueError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content")
                if isinstance(delta, list):
                    delta = "".join(i.get("text", "") for i in delta if isinstance(i, dict))
                if delta:
                    parts.append(delta)
                    yield _sse({"delta": delta})
            answer = "".join(parts).strip()
            if not answer:
                yield _sse({"error": "AI javobi bo‘sh qaytdi."})
                return
            history_id = save(answer)
            saved = True
            yield _sse({"done": True, "history_id": history_id, "thread_id": thread_id, "folder": folder,
                        "usage": usage_for(user_id, premium_active)})
        except GeneratorExit:
            partial = "".join(parts).strip()
            if partial and not saved:
                save(partial + "\n\n[Javob to‘xtatildi]")
            raise
        except Exception:
            app.logger.exception("AI stream failed")
            partial = "".join(parts).strip()
            if partial and not saved:
                save(partial)
            yield _sse({"error": "Javob oqimi uzildi. Qayta urinib ko‘ring."})
        finally:
            try:
                resp.close()
            except Exception:
                pass

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/ask", methods=["POST"])
@login_required
@limiter.limit("10 per minute; 120 per hour")
def ask():
    import urllib.error

    data = request.get_json(silent=True) or {}
    question = str(data.get("question", "")).strip()
    image_data = data.get("image")

    if not question and not image_data:
        return jsonify(error="Savol yozing yoki rasm tanlang."), 400
    user = current_user()
    want_stream = bool(data.get("stream"))
    thread_id = None
    if data.get("thread_id") not in (None, ""):
        try:
            thread_id = int(data.get("thread_id"))
        except (TypeError, ValueError):
            return jsonify(error="Suhbat identifikatori noto‘g‘ri."), 400
        with db() as conn:
            owned = conn.execute("SELECT 1 FROM history WHERE user_id=? AND thread_id=? LIMIT 1",
                                 (user["id"], thread_id)).fetchone()
        if not owned:
            return jsonify(error="Suhbat topilmadi."), 404
    premium_active = bool(user and user["premium_until"] and str(user["premium_until"]) > time.strftime("%Y-%m-%d %H:%M:%S"))
    max_question = 10000 if premium_active else 5000
    if len(question) > max_question:
        return jsonify(error=f"Savol {max_question} belgidan oshmasin."), 400
    usage = usage_for(user["id"], premium_active)
    if usage["remaining"] <= 0:
        return jsonify(error=f"Kunlik limit tugadi ({usage['limit']} ta so‘rov). { 'PRO limitidan foydalanish uchun obunani yangilang.' if not premium_active else 'Limit ertaga yangilanadi.'}", usage=usage, limit_reached=True), 429

    image_url = None
    if image_data:
        if not isinstance(image_data, str) or len(image_data) > 7_000_000:
            return jsonify(error="Rasm hajmi juda katta. 5 MB dan kichik rasm tanlang."), 413
        match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})", image_data)
        if not match:
            return jsonify(error="Faqat PNG, JPG yoki WEBP formatidagi rasm qabul qilinadi."), 400
        try:
            image_bytes = base64.b64decode(match.group(2), validate=True)
        except (ValueError, base64.binascii.Error):
            return jsonify(error="Rasm faylini o‘qib bo‘lmadi."), 400
        if not image_bytes or len(image_bytes) > 5 * 1024 * 1024:
            return jsonify(error="Rasm hajmi 5 MB dan oshmasin."), 413
        image_url = image_data
        if not question:
            question = "Ushbu rasmni tahlil qilib, undagi muhim narsalarni tushuntir."

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return jsonify(error="API kaliti topilmadi. .env faylini tekshiring."), 503

    endpoint = os.environ.get(
        "OPENAI_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    ).strip().rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        endpoint += "/chat/completions"

    model = os.environ.get("OPENAI_MODEL", "gemini-2.5-flash").strip()

    system_prompt = (
        "Sen CyberAI Pro nomli yagona, professional AI yordamchisisan. "
        "Asosan o‘zbek tilida aniq, foydali va tushunarli javob ber. "
        "Dasturlash, kod yozish va xatolarni tuzatish, umumiy savollar, "
        "kiberxavfsizlikning himoyaviy tomonlari va o‘quv laboratoriyalari bo‘yicha yordam ber. "
        "Kerak bo‘lsa sarlavha, qadamlar, kod bloklari va misollardan foydalan. "
        "Taxminni fakt sifatida ko‘rsatma. Faqat ruxsat etilgan tizimlarda sinov o‘tkazishni tavsiya qil. "
        "Begona akkauntga kirish, credential theft, zararli dastur yaratish yoki real tizimlarga "
        "ruxsatsiz hujum qilish bo‘yicha yo‘l-yo‘riq berma; xavfsiz va himoyaviy alternativalarni taklif et."
    )
    prior = []
    if thread_id is not None:
        with db() as conn:
            prior = conn.execute(
                "SELECT question, answer FROM history WHERE user_id=? AND thread_id=? ORDER BY id DESC LIMIT ?",
                (user["id"], thread_id, 12 if premium_active else 4)
            ).fetchall()
    messages = [{"role": "system", "content": system_prompt}]
    for item in reversed(prior):
        messages.append({"role": "user", "content": item["question"][:3500]})
        messages.append({"role": "assistant", "content": item["answer"][:6000]})
    if image_url:
        messages.append({"role": "user", "content": [
            {"type": "text", "text": question or "Ushbu rasmni tahlil qil."},
            {"type": "image_url", "image_url": {"url": image_url}}
        ]})
    else:
        messages.append({"role": "user", "content": question})
    payload_obj = {
        "model": model,
        "messages": messages,
        "temperature": 0.3
    }
    if want_stream:
        payload_obj["stream"] = True
    payload = json.dumps(payload_obj).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        method="POST"
    )

    if want_stream:
        return _ask_stream(req, user, premium_active, question, image_url, thread_id)

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))

        choices = result.get("choices", [])
        if not choices:
            app.logger.error("AI provider response contained no choices.")
            return jsonify(error="AI bo‘sh javob qaytardi. Model sozlamasini tekshiring."), 502

        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict)
            )
        answer = str(content).strip()

        if not answer:
            return jsonify(error="AI javobi bo‘sh qaytdi."), 502

    except urllib.error.HTTPError as e:
        details = e.read().decode("utf-8", errors="replace")[:1500]
        # API kaliti hech qachon logga chiqarilmaydi.
        app.logger.error("AI provider HTTP error: status=%s, details=%s", e.code, details)

        if e.code == 401:
            message = "API kaliti noto‘g‘ri yoki yaroqsiz. Kalitni tekshiring."
        elif e.code == 403:
            message = "API uchun ruxsat yo‘q. Kalit, loyiha yoki hududiy cheklovni tekshiring."
        elif e.code == 404:
            message = "Model yoki API manzili topilmadi. Terminaldagi AI provider HTTP error tafsilotini tekshiring."
        elif e.code == 429:
            message = "API kvotasi yoki so‘rov limiti tugagan."
        else:
            message = f"AI provayderi HTTP {e.code} xatosini qaytardi. Terminalni tekshiring."
        return jsonify(error=message), 502

    except urllib.error.URLError as e:
        app.logger.error("AI provider connection error: %s", str(e.reason))
        return jsonify(error="AI serveriga ulanib bo‘lmadi. Internet va API manzilini tekshiring."), 502

    except (TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        app.logger.exception("AI response parsing failed")
        return jsonify(error="AI javobini o‘qishda xatolik. Terminal loglarini tekshiring."), 502

    except Exception:
        app.logger.exception("Unexpected AI provider error")
        return jsonify(error="AI xizmatida kutilmagan xato. Terminal loglarini tekshiring."), 502

    with db() as conn:
        if thread_id is None:
            thread_id = conn.execute("SELECT COALESCE(MAX(thread_id),0)+1 FROM history").fetchone()[0]
        saved = conn.execute(
            "INSERT INTO history(user_id, question, answer, folder, thread_id) VALUES(?,?,?,?,?)",
            (user["id"], ("[Rasm] " if image_url else "") + question, answer, _guess_history_folder(question), thread_id)
        )
        history_id = saved.lastrowid
    usage = usage_for(user["id"], premium_active)
    return jsonify(answer=answer, configured=True, usage=usage, history_id=history_id, thread_id=thread_id, folder=_guess_history_folder(question)), 200


@app.route("/premium", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute", methods=["POST"])
def premium():
    user = current_user()
    if request.method == "POST":
        plan_key = request.form.get("plan", "")
        note = request.form.get("payment_note", "").strip()[:500]
        if plan_key not in PLANS or len(note) < 4:
            flash("Tarifni tanlang va to‘lov izohi/chek raqamini kiriting.", "error")
            return redirect(url_for("premium"))
        with db() as conn:
            pending = conn.execute("SELECT id FROM premium_requests WHERE user_id=? AND status='pending'", (user["id"],)).fetchone()
            if pending:
                flash("Sizda ko‘rib chiqilayotgan so‘rov bor. Admin javobini kuting.", "error")
            else:
                ref_code = "CAP-" + secrets.token_hex(4).upper()
                conn.execute("INSERT INTO premium_requests(user_id,plan_key,payment_note,reference_code) VALUES(?,?,?,?)", (user["id"], plan_key, note, ref_code))
                conn.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,?)", (user["id"], "PRO so‘rovi qabul qilindi", f"So‘rov raqami: {ref_code}. Admin tekshirganidan keyin natija shu yerda ko‘rinadi.", "billing"))
                flash(f"So‘rov yuborildi. Raqamingiz: {ref_code}. Admin tasdig‘ini kuting.", "success")
        return redirect(url_for("premium"))
    with db() as conn:
        requests_rows = conn.execute("SELECT * FROM premium_requests WHERE user_id=? ORDER BY id DESC LIMIT 10", (user["id"],)).fetchall()
    premium_active = bool(user["premium_until"] and str(user["premium_until"]) > time.strftime("%Y-%m-%d %H:%M:%S"))
    usage = usage_for(user["id"], premium_active)
    return render_template("premium.html", user=user, plans=PLANS, requests_rows=requests_rows, now_text=time.strftime("%Y-%m-%d %H:%M:%S"), usage=usage)

@app.route("/admin")
@login_required
@admin_required
def admin_panel():
    with db() as conn:
        rows = conn.execute("""SELECT p.*,u.username,u.email FROM premium_requests p JOIN users u ON u.id=p.user_id
            ORDER BY CASE p.status WHEN 'pending' THEN 0 ELSE 1 END, p.id DESC LIMIT 200""").fetchall()
        stats = {
            "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "pending": conn.execute("SELECT COUNT(*) FROM premium_requests WHERE status='pending'").fetchone()[0],
            "premium": conn.execute("SELECT COUNT(*) FROM users WHERE premium_until IS NOT NULL AND premium_until > datetime('now')").fetchone()[0],
            "users_today": conn.execute("SELECT COUNT(*) FROM users WHERE date(created_at)=date('now')").fetchone()[0],
            "chats_today": conn.execute("SELECT COUNT(*) FROM history WHERE date(created_at)=date('now')").fetchone()[0],
            "total_chats": conn.execute("SELECT COUNT(*) FROM history").fetchone()[0],
            "feedback_open": conn.execute("SELECT COUNT(*) FROM feedback WHERE status IN ('open','in_progress')").fetchone()[0],
            "unread_notifications": conn.execute("SELECT COUNT(*) FROM notifications WHERE is_read=0").fetchone()[0],
            "approved_value": sum(PLANS.get(r[0], {}).get("price", 0) for r in conn.execute("SELECT plan_key FROM premium_requests WHERE status='approved'").fetchall()),
        }
    return render_template("admin.html", user=current_user(), requests_rows=rows, plans=PLANS, stats=stats)

@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    q = request.args.get("q", "").strip()[:100]
    with db() as conn:
        if q:
            users = conn.execute("""SELECT id,username,email,created_at,is_admin,premium_until,
                CASE WHEN premium_until IS NOT NULL AND premium_until > datetime('now') THEN 1 ELSE 0 END AS premium_active
                FROM users WHERE username LIKE ? OR email LIKE ? ORDER BY id DESC LIMIT 200""",
                (f"%{q}%", f"%{q}%")).fetchall()
        else:
            users = conn.execute("""SELECT id,username,email,created_at,is_admin,premium_until,
                CASE WHEN premium_until IS NOT NULL AND premium_until > datetime('now') THEN 1 ELSE 0 END AS premium_active
                FROM users ORDER BY id DESC LIMIT 200""").fetchall()
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return render_template("admin_users.html", user=current_user(), users=users, q=q, total=total, plans=PLANS)

@app.route("/admin/users/<int:user_id>/grant", methods=["POST"])
@login_required
@admin_required
def grant_premium(user_id):
    plan_key = request.form.get("plan", "")
    plan = PLANS.get(plan_key)
    if not plan:
        flash("Tarifni tanlash kerak.", "error")
        return redirect(url_for("admin_users"))
    with db() as conn:
        target = conn.execute("SELECT id,username FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            abort(404)
        conn.execute("UPDATE users SET premium_until=datetime(CASE WHEN premium_until IS NOT NULL AND premium_until > datetime('now') THEN premium_until ELSE datetime('now') END, ?) WHERE id=?",
                     (f"+{plan['days']} days", user_id))
        conn.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,?)",
                     (user_id, "PRO obunangiz faollashtirildi", f"Admin sizga {plan['name']} PRO obunasini berdi.", "billing"))
    flash(f"{target['username']} foydalanuvchisiga {plan['name']} Pro obunasi berildi.", "success")
    return redirect(url_for("admin_users", q=request.form.get("q", "")))

@app.route("/admin/premium/<int:request_id>/<action>", methods=["POST"])
@login_required
@admin_required
def review_premium(request_id, action):
    if action not in ("approve", "reject"):
        abort(404)
    admin = current_user()
    with db() as conn:
        row = conn.execute("SELECT * FROM premium_requests WHERE id=?", (request_id,)).fetchone()
        if not row or row["status"] != "pending":
            flash("So‘rov topilmadi yoki oldin ko‘rib chiqilgan.", "error")
            return redirect(url_for("admin_panel"))
        if action == "approve":
            plan = PLANS.get(row["plan_key"])
            if not plan:
                flash("Tarif ma’lumoti topilmadi.", "error")
                return redirect(url_for("admin_panel"))
            conn.execute("UPDATE users SET premium_until=datetime(CASE WHEN premium_until IS NOT NULL AND premium_until > datetime('now') THEN premium_until ELSE datetime('now') END, ?) WHERE id=?",
                         (f"+{plan['days']} days", row["user_id"]))
            status = "approved"
        else:
            status = "rejected"
        conn.execute("UPDATE premium_requests SET status=?,reviewed_at=CURRENT_TIMESTAMP,reviewed_by=? WHERE id=?", (status, admin["id"], request_id))
        plan_name = PLANS.get(row["plan_key"], {}).get("name", row["plan_key"])
        notice_title = "PRO obunangiz faollashtirildi" if action == "approve" else "PRO so‘rovi rad etildi"
        notice_body = (f"{plan_name} tarifingiz tasdiqlandi. Obuna muddati: admin panelidagi profilingizda ko‘rinadi." if action == "approve" else "So‘rovingiz tasdiqlanmadi. To‘lov ma’lumotini tekshirib, kerak bo‘lsa qayta murojaat qiling.")
        conn.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,?)", (row["user_id"], notice_title, notice_body, "billing"))
    flash("Premium so‘rovi tasdiqlandi." if action == "approve" else "So‘rov rad etildi.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/notifications", methods=["GET", "POST"])
@login_required
@limiter.limit("15 per minute", methods=["POST"])
def notifications_page():
    user = current_user()
    if request.method == "POST":
        with db() as conn:
            conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user["id"],))
        flash("Bildirishnomalar o‘qilgan deb belgilandi.", "success")
        return redirect(url_for("notifications_page"))
    with db() as conn:
        items = conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100", (user["id"],)).fetchall()
        unread = conn.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0", (user["id"],)).fetchone()[0]
    return render_template("notifications.html", user=user, items=items, unread=unread)


@app.route("/admin/notifications", methods=["POST"])
@login_required
@admin_required
@limiter.limit("5 per minute")
def admin_broadcast_notification():
    title = request.form.get("title", "").strip()[:120]
    body = request.form.get("body", "").strip()[:1200]
    if len(title) < 3 or len(body) < 5:
        flash("Sarlavha va xabarni to‘liq kiriting.", "error")
        return redirect(url_for("admin_panel"))
    with db() as conn:
        conn.execute("INSERT INTO notifications(user_id,title,body,kind) SELECT id,?,?,? FROM users", (title, body, "announcement"))
    flash("Xabar barcha foydalanuvchilarga yuborildi.", "success")
    return redirect(url_for("admin_panel"))


@app.route("/support", methods=["GET", "POST"])
@login_required
@limiter.limit("5 per hour", methods=["POST"])
def support_page():
    user = current_user()
    if request.method == "POST":
        category = request.form.get("category", "feedback")
        subject = request.form.get("subject", "").strip()[:120]
        message = request.form.get("message", "").strip()[:3000]
        if category not in ("feedback", "bug", "idea", "billing") or len(subject) < 3 or len(message) < 10:
            flash("Tur, mavzu va kamida 10 belgili xabar kiriting.", "error")
            return redirect(url_for("support_page"))
        with db() as conn:
            conn.execute("INSERT INTO feedback(user_id,category,subject,message) VALUES(?,?,?,?)", (user["id"], category, subject, message))
            conn.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,?)", (user["id"], "Murojaat qabul qilindi", "Murojaatingiz support ro‘yxatiga yuborildi. Javob bo‘lsa shu yerda ko‘rasiz.", "support"))
        flash("Murojaatingiz yuborildi. Rahmat!", "success")
        return redirect(url_for("support_page"))
    with db() as conn:
        tickets = conn.execute("SELECT * FROM feedback WHERE user_id=? ORDER BY id DESC LIMIT 30", (user["id"],)).fetchall()
    return render_template("support.html", user=user, tickets=tickets)


@app.route("/admin/feedback", methods=["GET", "POST"])
@login_required
@admin_required
def admin_feedback():
    if request.method == "POST":
        ticket_id = request.form.get("ticket_id", type=int)
        status = request.form.get("status", "in_progress")
        reply = request.form.get("admin_reply", "").strip()[:2000]
        if status not in ("open", "in_progress", "resolved"):
            abort(400)
        with db() as conn:
            ticket = conn.execute("SELECT user_id,subject,admin_reply FROM feedback WHERE id=?", (ticket_id,)).fetchone()
            if not ticket:
                abort(404)
            conn.execute("UPDATE feedback SET status=?,admin_reply=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, reply or None, ticket_id))
            if reply and reply != (ticket["admin_reply"] or ""):
                conn.execute("INSERT INTO notifications(user_id,title,body,kind) VALUES(?,?,?,?)", (ticket["user_id"], "Murojaatingizga javob bor", f"{ticket['subject']}: {reply}", "support"))
        flash("Murojaat yangilandi.", "success")
        return redirect(url_for("admin_feedback"))
    with db() as conn:
        tickets = conn.execute("SELECT f.*,u.username,u.email FROM feedback f JOIN users u ON u.id=f.user_id ORDER BY CASE f.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END, f.id DESC LIMIT 200").fetchall()
    return render_template("admin_feedback.html", user=current_user(), tickets=tickets)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/health")
def health():
    return jsonify(status="ok")

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), debug=False)