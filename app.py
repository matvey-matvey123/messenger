import glob
import json
import os
import threading
import time
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

APP_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(APP_DIR, "users.json")
MESSAGES_FILE = os.path.join(APP_DIR, "messages.json")
COMPLAINTS_FILE = os.path.join(APP_DIR, "complaints.json")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
ANNOUNCEMENTS_FILE = os.path.join(APP_DIR, "announcements.json")
UPLOAD_DIR = os.path.join(APP_DIR, "uploads")
AVATAR_DIR = os.path.join(UPLOAD_DIR, "avatars")
MEDIA_DIR = os.path.join(UPLOAD_DIR, "media")
for d in (UPLOAD_DIR, AVATAR_DIR, MEDIA_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)
app.secret_key = "messenger-secret-key-change-me"
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

lock = threading.Lock()
last_seen = {}
ONLINE_TIMEOUT = 20
OWNER_LOGIN = "admin"
OWNER_NAME = "Матвей"
OWNER_PASSWORD_HASH = "scrypt:32768:8:1$pxHWi9utB1Eyq6pb$fff0c31432bcd17249ebc50b680075ac381bf47a7775ae7b04adc23bd46ce985fbcfa5c6bfffd964926c1dd885953d9e631bcbffbadfc31922244583e6ad81a8"
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".webm", ".mov"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXT = {".mp4", ".webm", ".mov"}

calls = {}
call_lock = threading.Lock()


# ---------- Data ----------

def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def load_messages():
    if not os.path.exists(MESSAGES_FILE):
        return []
    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_messages(msgs):
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(msgs, f, ensure_ascii=False, indent=2)


def load_complaints():
    if not os.path.exists(COMPLAINTS_FILE):
        return []
    try:
        with open(COMPLAINTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_complaints(comps):
    with open(COMPLAINTS_FILE, "w", encoding="utf-8") as f:
        json.dump(comps, f, ensure_ascii=False, indent=2)


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"title": "Мессенджер"}


def save_settings(s):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def load_announcements():
    if not os.path.exists(ANNOUNCEMENTS_FILE):
        return []
    try:
        with open(ANNOUNCEMENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_announcements(items):
    with open(ANNOUNCEMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def owner_user():
    return {
        "id": 1,
        "login": OWNER_LOGIN,
        "name": OWNER_NAME,
        "password": OWNER_PASSWORD_HASH,
        "is_admin": True,
        "blocked": [],
        "hidden": [],
        "avatar": "",
    }


def ensure_owner():
    with lock:
        users = load_users()
        changed = False
        found = None
        for u in users:
            if u["login"].lower() == OWNER_LOGIN:
                found = u
                break
        if found is None:
            users.append(owner_user())
            changed = True
        else:
            if not found.get("is_admin"):
                found["is_admin"] = True
                changed = True
            if not found.get("password"):
                found["password"] = OWNER_PASSWORD_HASH
                changed = True
            found.setdefault("blocked", [])
            found.setdefault("hidden", [])
        if changed:
            save_users(users)


def find_user(login):
    login = (login or "").strip().lower()
    for u in load_users():
        if u["login"].lower() == login:
            return u
    return None


def current_user():
    login = session.get("login")
    if not login:
        return None
    return find_user(login)


def touch(user):
    last_seen[user["login"]] = time.time()


def is_online(login):
    return time.time() - last_seen.get(login, 0) < ONLINE_TIMEOUT


def chat_key(a, b):
    return "private:" + ":".join(sorted([a.lower(), b.lower()]))


def is_owner_login(login):
    return (login or "").strip().lower() == OWNER_LOGIN


def user_role(u):
    if is_owner_login(u.get("login", "")):
        return "owner"
    role = u.get("role", "") or ""
    if role in ("senior_admin", "junior_admin"):
        return role
    return "admin" if u.get("is_admin") else ""


def can_manage_target(requester, target_login):
    if is_owner_login(target_login):
        return requester["login"].lower() == OWNER_LOGIN
    return True


def can_manage_roles(requester):
    return user_role(requester) in ("owner", "senior_admin")


def can_handle_complaints(requester):
    return user_role(requester) in ("owner", "senior_admin")


def can_mute(requester):
    return user_role(requester) in ("owner", "senior_admin")


def can_delete_account(requester):
    return user_role(requester) == "owner"


def public_info(u):
    hidden = u.get("role_hidden", False)
    return {
        "login": u["login"],
        "name": u["name"],
        "avatar": u.get("avatar", ""),
        "online": is_online(u["login"]),
        "is_admin": False if hidden else u.get("is_admin", False),
        "is_owner": False if hidden else is_owner_login(u["login"]),
        "role": "" if hidden else user_role(u),
        "muted": bool(u.get("muted_until") and u["muted_until"] > time.time()),
        "muted_until": u.get("muted_until"),
        "prefix": u.get("prefix", ""),
        "extension": u.get("extension", ""),
    }


def current_admin():
    user = current_user()
    if not user or not user.get("is_admin"):
        return None
    return user


def require_admin():
    user = current_admin()
    if not user:
        return None, (jsonify({"error": "Нет прав администратора"}), 403)
    return user, None


# ---------- Pages ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/uploads/<path:filename>")
def uploads(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------- Auth ----------

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:30]
    login = str(data.get("login", "")).strip()[:30].lower()
    password = str(data.get("password", ""))
    if not name or not login or not password:
        return jsonify({"error": "Заполните все поля"}), 400
    if len(password) < 4:
        return jsonify({"error": "Пароль слишком короткий (минимум 4 символа)"}), 400
    if find_user(login):
        return jsonify({"error": "Данный логин занят"}), 400
    ensure_owner()
    with lock:
        users = load_users()
        user = {
            "id": max([u["id"] for u in users], default=0) + 1,
            "login": login,
            "name": name,
            "password": generate_password_hash(password),
            "is_admin": False,
            "blocked": [],
            "hidden": [],
            "avatar": "",
        }
        users.append(user)
        save_users(users)
    if not session.get("login"):
        session["login"] = login
    last_seen[login] = time.time()
    return jsonify({"ok": True, "login": login, "name": name, "is_admin": user["is_admin"], "role": user_role(user)})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip()[:30].lower()
    password = str(data.get("password", ""))
    user = find_user(login)
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Неверный логин или пароль"}), 400
    session["login"] = user["login"]
    last_seen[user["login"]] = time.time()
    return jsonify({
        "ok": True, "login": user["login"], "name": user["name"],
        "is_admin": user.get("is_admin", False), "is_owner": is_owner_login(user["login"]),
        "role": user_role(user),
        "avatar": user.get("avatar", ""),
    })


@app.route("/api/logout", methods=["POST"])
def logout():
    login = session.get("login")
    if login:
        last_seen.pop(login, None)
        session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def me():
    login = session.get("login")
    if not login:
        return jsonify({"authenticated": False})
    user = find_user(login)
    if not user:
        return jsonify({"authenticated": False})
    return jsonify({
        "authenticated": True,
        "login": user["login"],
        "name": user["name"],
        "is_admin": user.get("is_admin", False),
        "is_owner": is_owner_login(user["login"]),
        "role": user_role(user),
        "avatar": user.get("avatar", ""),
        "blocked": user.get("blocked", []),
        "hidden": user.get("hidden", []),
        "role_hidden": user.get("role_hidden", False),
        "prefix": user.get("prefix", ""),
        "extension": user.get("extension", ""),
    })


# ---------- Users ----------

@app.route("/api/users")
def users():
    me_user = current_user()
    if not me_user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(me_user)
    blocked_me = [b.lower() for b in me_user.get("blocked", [])]
    hidden_me = [h.lower() for h in me_user.get("hidden", [])]
    result = []
    for u in load_users():
        info = public_info(u)
        info["iBlocked"] = u["login"].lower() in blocked_me
        info["blockedBy"] = False
        info["hidden"] = u["login"].lower() in hidden_me
        result.append(info)
    for item in result:
        target = find_user(item["login"])
        if target and me_user["login"].lower() in [b.lower() for b in target.get("blocked", [])]:
            item["blockedBy"] = True

    group_call = None
    with call_lock:
        for r in calls.values():
            if r["type"] == "group" and r["state"] != "idle":
                group_call = {
                    "room_id": r["id"],
                    "host": r["host"],
                    "count": len(r["participants"]),
                }
                break
    return jsonify({
        "users": result,
        "title": load_settings().get("title", "Мессенджер"),
        "group_call": group_call,
    })


@app.route("/api/users/block", methods=["POST"])
def block_user():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    if login == user["login"].lower():
        return jsonify({"error": "Нельзя заблокировать себя"}), 400
    if not find_user(login):
        return jsonify({"error": "Пользователь не найден"}), 404
    if not can_manage_target(user, login):
        return jsonify({"error": "Нельзя заблокировать владельца"}), 403
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == user["login"].lower():
                if login not in [b.lower() for b in u.get("blocked", [])]:
                    u["blocked"].append(login)
        save_users(users)
    return jsonify({"ok": True})


@app.route("/api/users/unblock", methods=["POST"])
def unblock_user():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == user["login"].lower():
                u["blocked"] = [b for b in u.get("blocked", []) if b.lower() != login]
        save_users(users)
    return jsonify({"ok": True})


@app.route("/api/users/hide", methods=["POST"])
def hide_user():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    if not find_user(login):
        return jsonify({"error": "Пользователь не найден"}), 404
    if not can_manage_target(user, login):
        return jsonify({"error": "Нельзя скрыть владельца"}), 403
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == user["login"].lower():
                if login not in [h.lower() for h in u.get("hidden", [])]:
                    u["hidden"].append(login)
        save_users(users)
    return jsonify({"ok": True})


@app.route("/api/users/unhide", methods=["POST"])
def unhide_user():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == user["login"].lower():
                u["hidden"] = [h for h in u.get("hidden", []) if h.lower() != login]
        save_users(users)
    return jsonify({"ok": True})


# ---------- Messages ----------

@app.route("/api/messages", methods=["GET"])
def get_messages():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    chat = request.args.get("chat", "public")
    after = request.args.get("after", default=0, type=int)
    mod_after = request.args.get("mod_after", default=0, type=int)
    with lock:
        msgs = load_messages()
        if chat == "public":
            blocked = [b.lower() for b in user.get("blocked", [])]
            base = [m for m in msgs if m["chat"] == "public" and m["login"].lower() not in blocked]
        else:
            with_ = request.args.get("with", "").strip()
            if not with_:
                return jsonify({"error": "Укажите собеседника"}), 400
            if not find_user(with_):
                return jsonify({"error": "Пользователь не найден"}), 404
            key = chat_key(user["login"], with_)
            base = [m for m in msgs if m["chat"] == key]
        result = [m for m in base if m["id"] > after]
        if mod_after:
            result += [m for m in base if m["id"] <= after and m.get("mod_time", 0) >= mod_after]
        return jsonify(result)


@app.route("/api/messages", methods=["POST"])
def post_message():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()[:1000]
    if not text:
        return jsonify({"error": "Сообщение не может быть пустым"}), 400

    chat = data.get("chat", "public")
    target = None

    if (is_owner_login(user["login"]) or user_role(user) == "senior_admin") and chat == "public":
        cmd_result = handle_owner_command(user, text)
        if cmd_result:
            return jsonify(cmd_result)

    if chat == "public":
        if user.get("muted_until") and user["muted_until"] > time.time():
            return jsonify({"error": "Вы замьючены до " + time.strftime("%H:%M", time.localtime(user["muted_until"]))}), 403
    else:
        to = str(data.get("to", "")).strip()
        target = find_user(to)
        if not target:
            return jsonify({"error": "Пользователь не найден"}), 404
        if user["login"].lower() in [b.lower() for b in target.get("blocked", [])]:
            return jsonify({"error": "Пользователь заблокировал вас"}), 403

    with lock:
        msgs = load_messages()
        msg = {
            "id": max([m["id"] for m in msgs], default=0) + 1,
            "chat": "public" if chat == "public" else chat_key(user["login"], target["login"]),
            "login": user["login"],
            "name": user["name"],
            "admin": user.get("is_admin", False),
            "role": user_role(user),
            "type": "text",
            "text": text,
            "time": int(time.time()),
            "read_by": [],
        }
        msgs.append(msg)
        save_messages(msgs)
        return jsonify(msg)


def handle_owner_command(user, text):
    if not text.startswith("/"):
        return None
    parts = text.split(None, 2)
    cmd = parts[0].lower()

    if cmd == "/ob":
        if not is_owner_login(user["login"]):
            return {"error": "Команда /ob доступна только владельцу"}
        announcement_text = parts[1] if len(parts) > 1 else ""
        if not announcement_text:
            return {"error": "Укажите текст объявления: /ob текст"}
        with lock:
            items = load_announcements()
            item = {
                "id": max([i["id"] for i in items], default=0) + 1,
                "text": announcement_text,
                "author": user["login"],
                "author_name": user["name"],
                "time": int(time.time()),
            }
            items.append(item)
            save_announcements(items)
            msgs = load_messages()
            msg = {
                "id": max([m["id"] for m in msgs], default=0) + 1,
                "chat": "public",
                "login": user["login"],
                "name": user["name"],
                "admin": True,
                "role": "owner",
                "type": "text",
                "text": "📢 ОБЪЯВЛЕНИЕ: " + announcement_text,
                "time": int(time.time()),
                "is_announcement": True,
                "read_by": [],
            }
            msgs.append(msg)
            save_messages(msgs)
        return msg

    if cmd == "/mute":
        if len(parts) < 2:
            return {"error": "Использование: /mute <логин> <время> (например: /mute bob 15m, /mute bob 1h, /mute bob 1d)"}
        target_login = parts[1].strip().lower()
        time_str = parts[2] if len(parts) > 2 else "5m"
        minutes = parse_duration(time_str)
        if minutes <= 0:
            return {"error": "Неверный формат времени. Используйте: 15m, 1h, 1d"}
        if not find_user(target_login):
            return {"error": "Пользователь @" + target_login + " не найден"}
        with lock:
            users = load_users()
            for u in users:
                if u["login"].lower() == target_login:
                    u["muted_until"] = int(time.time()) + minutes * 60
            save_users(users)
        return {"ok": True, "mute_result": "@" + target_login + " замьючен на " + format_duration(minutes)}

    if cmd == "/admin":
        if not is_owner_login(user["login"]):
            return {"error": "Команда /admin доступна только владельцу"}
        if len(parts) < 2:
            return {"error": "Использование: /admin <логин>"}
        target_login = parts[1].strip().lower()
        if not find_user(target_login):
            return {"error": "Пользователь @" + target_login + " не найден"}
        with lock:
            users = load_users()
            for u in users:
                if u["login"].lower() == target_login:
                    u["is_admin"] = True
                    u["role"] = "junior_admin"
            save_users(users)
        return {"ok": True, "mute_result": "@" + target_login + " теперь младший админ"}

    return None


def parse_duration(s):
    s = s.strip().lower()
    if s.endswith("m"):
        try: return int(s[:-1])
        except: return 0
    if s.endswith("h"):
        try: return int(s[:-1]) * 60
        except: return 0
    if s.endswith("d"):
        try: return int(s[:-1]) * 1440
        except: return 0
    try: return int(s)
    except: return 0


def format_duration(minutes):
    if minutes < 60:
        return str(minutes) + " мин"
    if minutes < 1440:
        h = minutes // 60
        m = minutes % 60
        return str(h) + " ч" + (" " + str(m) + " мин" if m else "")
    d = minutes // 1440
    h = (minutes % 1440) // 60
    return str(d) + " д" + (" " + str(h) + " ч" if h else "")


@app.route("/api/messages/upload", methods=["POST"])
def upload_message():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    chat = request.form.get("chat", "public")
    msg_chat = "public"
    target = None
    if chat == "public":
        if user.get("muted_until") and user["muted_until"] > time.time():
            return jsonify({"error": "Вы замьючены"}), 403
    else:
        to = str(request.form.get("to", "")).strip()
        target = find_user(to)
        if not target:
            return jsonify({"error": "Пользователь не найден"}), 404
        if target["login"].lower() in [b.lower() for b in user.get("blocked", [])]:
            return jsonify({"error": "Вы заблокировали этого пользователя"}), 403
        if user["login"].lower() in [b.lower() for b in target.get("blocked", [])]:
            return jsonify({"error": "Пользователь заблокировал вас"}), 403
        msg_chat = chat_key(user["login"], target["login"])

    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Файл не передан"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"error": "Недопустимый формат файла"}), 400
    kind = "video" if ext in VIDEO_EXT else "image"

    with lock:
        msgs = load_messages()
        msg = {
            "id": max([m["id"] for m in msgs], default=0) + 1,
            "chat": msg_chat,
            "login": user["login"],
            "name": user["name"],
            "admin": user.get("is_admin", False),
            "role": user_role(user),
            "type": kind,
            "time": int(time.time()),
            "read_by": [],
        }
        fname = str(msg["id"]) + "_" + uuid.uuid4().hex[:6] + ext
        path = os.path.join(MEDIA_DIR, fname)
        f.save(path)
        msg["file"] = "/uploads/media/" + fname
        msgs.append(msg)
        save_messages(msgs)
        return jsonify(msg)


@app.route("/api/messages/edit", methods=["POST"])
def edit_message():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    data = request.get_json(silent=True) or {}
    try:
        mid = int(data.get("id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректный id"}), 400
    text = str(data.get("text") or "").strip()[:1000]
    if not text:
        return jsonify({"error": "Сообщение не может быть пустым"}), 400
    with lock:
        msgs = load_messages()
        for m in msgs:
            if m["id"] == mid:
                if m["login"].lower() != user["login"].lower() and not user.get("is_admin"):
                    return jsonify({"error": "Можно редактировать только свои сообщения"}), 403
                if m.get("deleted"):
                    return jsonify({"error": "Сообщение удалено"}), 400
                m["text"] = text
                m["edited"] = True
                m["edited_time"] = int(time.time())
                m["mod_time"] = m["edited_time"]
                save_messages(msgs)
                return jsonify(m)
        return jsonify({"error": "Сообщение не найдено"}), 404


@app.route("/api/messages/delete", methods=["POST"])
def delete_message():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    data = request.get_json(silent=True) or {}
    try:
        mid = int(data.get("id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректный id"}), 400
    with lock:
        msgs = load_messages()
        for m in msgs:
            if m["id"] == mid:
                if m.get("deleted"):
                    if not user.get("is_admin"):
                        return jsonify({"error": "Можно удалять только свои сообщения"}), 403
                    msgs = [x for x in msgs if x["id"] != mid]
                    save_messages(msgs)
                    return jsonify({"id": mid, "permanently_deleted": True})
                if m["login"].lower() != user["login"].lower() and not user.get("is_admin"):
                    return jsonify({"error": "Можно удалять только свои сообщения"}), 403
                m["deleted"] = True
                m["deleted_time"] = int(time.time())
                m["mod_time"] = m["deleted_time"]
                save_messages(msgs)
                return jsonify(m)
        return jsonify({"error": "Сообщение не найдено"}), 404


# ---------- Profile ----------

@app.route("/api/profile/name", methods=["POST"])
def profile_name():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:30]
    if not name:
        return jsonify({"error": "Имя не может быть пустым"}), 400
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == user["login"].lower():
                u["name"] = name
        save_users(users)
    return jsonify({"ok": True, "name": name})


@app.route("/api/profile/password", methods=["POST"])
def profile_password():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    current = str(data.get("current", ""))
    new = str(data.get("new", ""))
    if not check_password_hash(user["password"], current):
        return jsonify({"error": "Неверный текущий пароль"}), 403
    if len(new) < 4:
        return jsonify({"error": "Новый пароль слишком короткий (минимум 4 символа)"}), 400
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == user["login"].lower():
                u["password"] = generate_password_hash(new)
        save_users(users)
    return jsonify({"ok": True})


@app.route("/api/profile/role_hidden", methods=["POST"])
def profile_role_hidden():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    hide = bool(data.get("hide"))
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == user["login"].lower():
                u["role_hidden"] = hide
        save_users(users)
    return jsonify({"ok": True, "role_hidden": hide})


@app.route("/api/admin/prefix", methods=["POST"])
def admin_set_prefix():
    admin, err = require_admin()
    if err:
        return err
    if not can_manage_roles(admin):
        return jsonify({"error": "Недостаточно прав"}), 403
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    prefix = str(data.get("prefix", "")).strip()[:50]
    if not login:
        return jsonify({"error": "Укажите логин"}), 400
    if not find_user(login):
        return jsonify({"error": "Пользователь не найден"}), 404
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == login:
                u["prefix"] = prefix
        save_users(users)
    return jsonify({"ok": True, "prefix": prefix})


@app.route("/api/admin/extension", methods=["POST"])
def admin_set_extension():
    admin, err = require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    extension = str(data.get("extension", "")).strip()[:20]
    if not login:
        return jsonify({"error": "Укажите логин"}), 400
    if not find_user(login):
        return jsonify({"error": "Пользователь не найден"}), 404
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == login:
                u["extension"] = extension
        save_users(users)
    return jsonify({"ok": True, "extension": extension})


@app.route("/api/profile/avatar", methods=["POST"])
def profile_avatar():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Файл не передан"}), 400
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in IMAGE_EXT:
        return jsonify({"error": "Аватарка должна быть картинкой (jpg, png, gif, webp)"}), 400
    fname = secure_filename(user["login"].lower()) + ext
    for old in glob.glob(os.path.join(AVATAR_DIR, secure_filename(user["login"].lower()) + ".*")):
        try:
            os.remove(old)
        except OSError:
            pass
    f.save(os.path.join(AVATAR_DIR, fname))
    avatar = "/uploads/avatars/" + fname
    with lock:
        users = load_users()
        for u in users:
            if u["login"].lower() == user["login"].lower():
                u["avatar"] = avatar
        save_users(users)
    return jsonify({"ok": True, "avatar": avatar})


# ---------- Settings ----------

@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())


@app.route("/api/settings/title", methods=["POST"])
def set_title():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    if not is_owner_login(user["login"]):
        return jsonify({"error": "Менять название может только владелец"}), 403
    data = request.get_json(silent=True) or {}
    title = str(data.get("title", "")).strip()[:40]
    if not title:
        return jsonify({"error": "Название не может быть пустым"}), 400
    with lock:
        s = load_settings()
        s["title"] = title
        save_settings(s)
    return jsonify({"ok": True, "title": title})


# ---------- Admin ----------

@app.route("/api/admin/status")
def admin_status():
    user = current_admin()
    if user:
        return jsonify({"is_admin": True, "role": user_role(user)})
    return jsonify({"is_admin": False, "role": ""})


@app.route("/api/admin/users")
def admin_users():
    _, err = require_admin()
    if err:
        return err
    result = []
    for u in load_users():
        info = public_info(u)
        info["blocked_count"] = len(u.get("blocked", []))
        info["hidden_count"] = len(u.get("hidden", []))
        result.append(info)
    result.sort(key=lambda x: (not x["is_admin"], x["login"].lower()))
    return jsonify(result)


@app.route("/api/admin/promote", methods=["POST"])
def admin_promote():
    admin, err = require_admin()
    if err:
        return err
    if not can_manage_roles(admin):
        return jsonify({"error": "Недостаточно прав"}), 403
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    role = str(data.get("role", "junior_admin")).strip()
    if role not in ("junior_admin", "senior_admin"):
        return jsonify({"error": "Недопустимая роль"}), 400
    if not login:
        return jsonify({"error": "Укажите логин"}), 400
    if not can_manage_target(admin, login):
        return jsonify({"error": "Нельзя менять роль владельца"}), 403
    if user_role(admin) == "senior_admin" and role == "senior_admin":
        return jsonify({"error": "Назначать старших админов может только владелец"}), 403
    with lock:
        users = load_users()
        found = False
        for u in users:
            if u["login"].lower() == login:
                u["is_admin"] = True
                u["role"] = role
                found = True
        if not found:
            return jsonify({"error": "Пользователь не найден"}), 404
        save_users(users)
    return jsonify({"ok": True})


@app.route("/api/admin/demote", methods=["POST"])
def admin_demote():
    admin, err = require_admin()
    if err:
        return err
    if not can_manage_roles(admin):
        return jsonify({"error": "Недостаточно прав"}), 403
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    if login == admin["login"].lower():
        return jsonify({"error": "Нельзя разжаловать самого себя"}), 400
    if not can_manage_target(admin, login):
        return jsonify({"error": "Нельзя менять роль владельца"}), 403
    with lock:
        users = load_users()
        found = False
        for u in users:
            if u["login"].lower() == login:
                u["is_admin"] = False
                u.pop("role", None)
                found = True
        if not found:
            return jsonify({"error": "Пользователь не найден"}), 404
        save_users(users)
    return jsonify({"ok": True})


@app.route("/api/admin/delete", methods=["POST"])
def admin_delete():
    admin, err = require_admin()
    if err:
        return err
    if not can_delete_account(admin):
        return jsonify({"error": "Удалять аккаунты может только владелец"}), 403
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    if login == admin["login"].lower():
        return jsonify({"error": "Нельзя удалить самого себя"}), 400
    if not can_manage_target(admin, login):
        return jsonify({"error": "Нельзя удалить владельца"}), 403
    with lock:
        users = load_users()
        before = len(users)
        users = [u for u in users if u["login"].lower() != login]
        if len(users) == before:
            return jsonify({"error": "Пользователь не найден"}), 404
        for u in users:
            u["blocked"] = [b for b in u.get("blocked", []) if b.lower() != login]
            u["hidden"] = [h for h in u.get("hidden", []) if h.lower() != login]
        save_users(users)

        msgs = load_messages()
        msgs = [m for m in msgs if m["login"].lower() != login]
        save_messages(msgs)

        comps = load_complaints()
        comps = [c for c in comps if c.get("target", "").lower() != login]
        save_complaints(comps)

        last_seen.pop(login, None)
        for old in glob.glob(os.path.join(AVATAR_DIR, secure_filename(login) + ".*")):
            try:
                os.remove(old)
            except OSError:
                pass
    return jsonify({"ok": True})


@app.route("/api/admin/mute", methods=["POST"])
def admin_mute():
    admin, err = require_admin()
    if err:
        return err
    if not can_mute(admin):
        return jsonify({"error": "Недостаточно прав"}), 403
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    try:
        minutes = max(1, min(int(data.get("minutes", 5)), 1440))
    except (TypeError, ValueError):
        minutes = 5
    if not can_manage_target(admin, login):
        return jsonify({"error": "Нельзя замутить владельца"}), 403
    with lock:
        users = load_users()
        found = False
        for u in users:
            if u["login"].lower() == login:
                u["muted_until"] = int(time.time()) + minutes * 60
                found = True
        if not found:
            return jsonify({"error": "Пользователь не найден"}), 404
        save_users(users)
    return jsonify({"ok": True, "muted_until": int(time.time()) + minutes * 60})


@app.route("/api/admin/unmute", methods=["POST"])
def admin_unmute():
    admin, err = require_admin()
    if err:
        return err
    if not can_mute(admin):
        return jsonify({"error": "Недостаточно прав"}), 403
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    with lock:
        users = load_users()
        found = False
        for u in users:
            if u["login"].lower() == login:
                u.pop("muted_until", None)
                found = True
        if not found:
            return jsonify({"error": "Пользователь не найден"}), 404
        save_users(users)
    return jsonify({"ok": True})


@app.route("/api/complaints", methods=["POST"])
def add_complaint():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    data = request.get_json(silent=True) or {}
    try:
        mid = int(data.get("message_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректный id сообщения"}), 400
    if mid <= 0:
        return jsonify({"error": "Укажите id сообщения"}), 400
    with lock:
        msgs = load_messages()
        msg = next((m for m in msgs if m["id"] == mid), None)
        if not msg:
            return jsonify({"error": "Сообщение не найдено"}), 404
        target_login = msg["login"].lower()
        if target_login == user["login"].lower():
            return jsonify({"error": "Нельзя пожаловаться на своё сообщение"}), 400
        comps = load_complaints()
        existing = [c for c in comps if c.get("target") == target_login and c.get("author") == user["login"].lower() and not c.get("resolved")]
        if existing:
            return jsonify({"error": "Вы уже отправляли жалобу на этого пользователя"}), 400
        comp = {
            "id": max([c["id"] for c in comps], default=0) + 1,
            "message_id": mid,
            "chat": msg["chat"],
            "target": target_login,
            "target_name": msg["name"],
            "author": user["login"].lower(),
            "text": msg.get("text") or msg.get("file") or "",
            "time": int(time.time()),
            "resolved": False,
        }
        comps.append(comp)
        save_complaints(comps)
    return jsonify({"ok": True, "id": comp["id"]})


@app.route("/api/admin/complaints")
def admin_complaints():
    _, err = require_admin()
    if err:
        return err
    if not can_handle_complaints(current_admin()):
        return jsonify({"error": "Недостаточно прав"}), 403
    comps = [c for c in load_complaints() if not c.get("resolved")]
    result = []
    for c in comps:
        item = dict(c)
        target = find_user(c.get("target", ""))
        author = find_user(c.get("author", ""))
        item["target_exists"] = bool(target)
        item["author_name"] = author["name"] if author else c.get("author", "")
        item["author_login"] = c.get("author", "")
        item["avatar"] = target.get("avatar", "") if target else ""
        result.append(item)
    result.sort(key=lambda x: -x["time"])
    return jsonify(result)


@app.route("/api/admin/complaints/resolve", methods=["POST"])
def resolve_complaint():
    _, err = require_admin()
    if err:
        return err
    if not can_handle_complaints(current_admin()):
        return jsonify({"error": "Недостаточно прав"}), 403
    data = request.get_json(silent=True) or {}
    try:
        cid = int(data.get("id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректный id"}), 400
    with lock:
        comps = load_complaints()
        for c in comps:
            if c["id"] == cid:
                c["resolved"] = True
                c["resolved_by"] = current_admin()["login"]
                save_complaints(comps)
                return jsonify({"ok": True})
        return jsonify({"error": "Жалоба не найдена"}), 404


@app.route("/api/admin/complaints/delete", methods=["POST"])
def delete_complaint():
    _, err = require_admin()
    if err:
        return err
    if not can_handle_complaints(current_admin()):
        return jsonify({"error": "Недостаточно прав"}), 403
    data = request.get_json(silent=True) or {}
    try:
        cid = int(data.get("id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Некорректный id"}), 400
    with lock:
        comps = load_complaints()
        before = len(comps)
        comps = [c for c in comps if c["id"] != cid]
        if len(comps) == before:
            return jsonify({"error": "Жалоба не найдена"}), 404
        save_complaints(comps)
    return jsonify({"ok": True})


@app.route("/api/admin/user/chats")
def admin_user_chats():
    _, err = require_admin()
    if err:
        return err
    target = find_user(request.args.get("user", ""))
    if not target:
        return jsonify({"error": "Пользователь не найден"}), 404
    with lock:
        msgs = load_messages()
        partners = {}
        for m in msgs:
            if not m["chat"].startswith("private:"):
                continue
            parts = m["chat"].split(":", 1)[1].split(":")
            if target["login"].lower() in parts:
                other = parts[0] if parts[1] == target["login"].lower() else parts[1]
                if other not in partners or m["id"] > partners[other]["last_id"]:
                    partners[other] = {"last_id": m["id"], "text": m["text"], "time": m["time"]}
        result = []
        for other, info in partners.items():
            u = find_user(other)
            result.append({
                "login": other,
                "name": u["name"] if u else "Удалён",
                "exists": bool(u),
                "last_text": info["text"],
                "last_time": info["time"],
            })
        result.sort(key=lambda x: -x["last_time"])
        return jsonify(result)


@app.route("/api/admin/chat")
def admin_chat():
    _, err = require_admin()
    if err:
        return err
    user = request.args.get("user", "").strip()
    with_ = request.args.get("with", "").strip()
    if not user or not with_:
        return jsonify({"error": "Укажите обоих участников"}), 400
    key = chat_key(user, with_)
    with lock:
        msgs = [m for m in load_messages() if m["chat"] == key]
        return jsonify(msgs)


# ---------- Announcements ----------

@app.route("/api/announcements")
def get_announcements():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    items = load_announcements()
    items.sort(key=lambda x: -x["time"])
    return jsonify(items[:50])


@app.route("/api/announcements/add", methods=["POST"])
def add_announcement():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    if not is_owner_login(user["login"]):
        return jsonify({"error": "Объявления может писать только владелец"}), 403
    data = request.get_json(silent=True) or {}
    text = str(data.get("text", "")).strip()[:500]
    if not text:
        return jsonify({"error": "Текст не может быть пустым"}), 400
    with lock:
        items = load_announcements()
        item = {
            "id": max([i["id"] for i in items], default=0) + 1,
            "text": text,
            "author": user["login"],
            "author_name": user["name"],
            "time": int(time.time()),
        }
        items.append(item)
        save_announcements(items)
    return jsonify(item)


# ---------- Private chats list ----------

@app.route("/api/privates")
def get_privates():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    with lock:
        msgs = load_messages()
        partners = {}
        for m in msgs:
            if not m["chat"].startswith("private:"):
                continue
            parts = m["chat"].split(":", 1)[1].split(":")
            if user["login"].lower() not in [p.lower() for p in parts]:
                continue
            other = parts[0] if parts[1].lower() == user["login"].lower() else parts[1]
            key = other.lower()
            if key not in partners or m["id"] > partners[key]["last_id"]:
                partners[key] = {"last_id": m["id"], "text": m.get("text", ""), "time": m["time"], "type": m.get("type", "text"), "deleted": m.get("deleted", False), "sender": m["login"]}
        result = []
        for other, info in partners.items():
            u = find_user(other)
            result.append({
                "login": other,
                "name": u["name"] if u else "Удалён",
                "avatar": u.get("avatar", "") if u else "",
                "online": is_online(other),
                "last_text": "🗑 Сообщение удалено" if info["deleted"] else ("📷 Фото" if info["type"] == "image" else "📹 Видео" if info["type"] == "video" else info["text"]),
                "last_time": info["time"],
                "sender": info["sender"],
            })
        result.sort(key=lambda x: -x["last_time"])
        return jsonify(result)


# ---------- Read receipts ----------

@app.route("/api/messages/read", methods=["POST"])
def mark_read():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    chat = str(data.get("chat", "")).strip()
    if not chat:
        return jsonify({"error": "Укажите чат"}), 400
    with lock:
        msgs = load_messages()
        count = 0
        for m in msgs:
            if m["chat"] == chat and user["login"] not in m.get("read_by", []):
                m.setdefault("read_by", []).append(user["login"])
                count += 1
        if count:
            save_messages(msgs)
    return jsonify({"ok": True, "count": count})


# ---------- Calls ----------

def prune_calls():
    t = time.time()
    for rid in list(calls.keys()):
        r = calls[rid]
        if r["state"] == "idle" and t - r.get("created", t) > 300:
            del calls[rid]


@app.route("/api/calls/start", methods=["POST"])
def call_start():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    data = request.get_json(silent=True) or {}
    ctype = data.get("type", "private")
    with call_lock:
        prune_calls()
        if ctype == "private":
            to = str(data.get("to", "")).strip()
            target = find_user(to)
            if not target:
                return jsonify({"error": "Пользователь не найден"}), 404
            if target["login"].lower() in [b.lower() for b in user.get("blocked", [])]:
                return jsonify({"error": "Вы заблокировали этого пользователя"}), 403
            if user["login"].lower() in [b.lower() for b in target.get("blocked", [])]:
                return jsonify({"error": "Пользователь заблокировал вас"}), 403
            rid = "p:" + ":".join(sorted([user["login"].lower(), target["login"].lower()]))
            room = calls.get(rid)
            if not room or room["state"] == "idle":
                room = {
                    "id": rid,
                    "type": "private",
                    "host": user["login"],
                    "video": bool(data.get("video", True)),
                    "state": "ringing",
                    "created": time.time(),
                    "participants": {user["login"]: {"joined": time.time(), "muted": False}},
                    "signals": [],
                }
                calls[rid] = room
            return jsonify({"room_id": rid, "state": room["state"], "video": room["video"]})
        else:
            if not user.get("is_admin"):
                return jsonify({"error": "Созвон в общем чате могут начинать только админы"}), 403
            rid = "g:" + uuid.uuid4().hex[:8]
            room = {
                "id": rid,
                "type": "group",
                "host": user["login"],
                "video": True,
                "state": "active",
                "created": time.time(),
                "participants": {user["login"]: {"joined": time.time(), "muted": False}},
                "signals": [],
            }
            calls[rid] = room
            return jsonify({"room_id": rid, "state": "active", "video": True})


@app.route("/api/calls/mine")
def calls_mine():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    with call_lock:
        prune_calls()
        result = []
        for r in calls.values():
            me_in = user["login"] in r["participants"]
            if r["type"] == "private" and r["state"] == "ringing" and not me_in:
                pair = r["id"][2:].split(":")
                if user["login"].lower() not in pair:
                    continue
                caller = find_user(r["host"])
                result.append({
                    "id": r["id"], "type": "private", "state": "ringing", "me_in": False,
                    "host": r["host"], "video": r["video"],
                    "caller_name": caller["name"] if caller else r["host"],
                    "caller_avatar": caller.get("avatar", "") if caller else "",
                })
            elif me_in:
                parts = []
                for p_login, p in r["participants"].items():
                    pu = find_user(p_login)
                    parts.append({
                        "login": p_login,
                        "name": pu["name"] if pu else p_login,
                        "avatar": pu.get("avatar", "") if pu else "",
                        "online": is_online(p_login),
                    })
                result.append({
                    "id": r["id"], "type": r["type"], "state": r["state"], "me_in": True,
                    "host": r["host"], "video": r["video"], "participants": parts,
                })
        return jsonify(result)


@app.route("/api/calls/join", methods=["POST"])
def call_join():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    data = request.get_json(silent=True) or {}
    rid = str(data.get("room_id", ""))
    with call_lock:
        room = calls.get(rid)
        if not room or room["state"] == "idle":
            return jsonify({"error": "Звонок уже завершён"}), 404
        room["participants"][user["login"]] = {"joined": time.time(), "muted": False}
        room["state"] = "active"
        return jsonify({"ok": True})


@app.route("/api/calls/leave", methods=["POST"])
def call_leave():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    rid = str(data.get("room_id", ""))
    with call_lock:
        room = calls.get(rid)
        if not room:
            return jsonify({"ok": True})
        room["participants"].pop(user["login"], None)
        if room["type"] == "private" and room["state"] == "ringing" and len(room["participants"]) < 2:
            room["state"] = "idle"
        if room["host"] not in room["participants"]:
            room["state"] = "idle"
        if not room["participants"]:
            calls.pop(rid, None)
        return jsonify({"ok": True})


@app.route("/api/calls/reject", methods=["POST"])
def call_reject():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    data = request.get_json(silent=True) or {}
    rid = str(data.get("room_id", ""))
    with call_lock:
        room = calls.get(rid)
        if room:
            room["state"] = "idle"
        return jsonify({"ok": True})


@app.route("/api/calls/signal", methods=["POST"])
def call_signal():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    data = request.get_json(silent=True) or {}
    rid = str(data.get("room_id", ""))
    target = str(data.get("target", "")).strip().lower()
    payload = data.get("data")
    with call_lock:
        room = calls.get(rid)
        if not room:
            return jsonify({"error": "Звонок завершён"}), 404
        room["signals"].append({"target": target, "from": user["login"], "data": payload, "ts": time.time()})
        if len(room["signals"]) > 200:
            del room["signals"][:-200]
        return jsonify({"ok": True})


@app.route("/api/calls/signals")
def call_signals():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    rid = request.args.get("room_id", "")
    with call_lock:
        room = calls.get(rid)
        if not room:
            return jsonify([])
        mine = [{"from": s["from"], "data": s["data"]} for s in room["signals"] if s["target"] == user["login"].lower()]
        room["signals"] = [s for s in room["signals"] if s["target"] != user["login"].lower()]
        return jsonify(mine)


# ---------- Main ----------

ensure_owner()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
