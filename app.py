import json
import os
import threading
import time

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(APP_DIR, "users.json")
MESSAGES_FILE = os.path.join(APP_DIR, "messages.json")

app = Flask(__name__)
app.secret_key = "messenger-secret-key-change-me"

lock = threading.Lock()
last_seen = {}
ONLINE_TIMEOUT = 20
ADMIN_PASSWORD = "mesenger123321"


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


def find_user(login):
    login = (login or "").strip().lower()
    for u in load_users():
        if u["login"].lower() == login:
            return u
    return None


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


def current_admin():
    user = current_user()
    if not user or not user.get("is_admin"):
        return None
    return user


def require_admin():
    user = current_admin()
    if not user:
        return None, (jsonify({"error": "Нет прав администратора"}), 403)
    if not session.get("admin_panel"):
        return None, (jsonify({"error": "Требуется пароль администратора"}), 403)
    return user, None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:30]
    login = str(data.get("login", "")).strip()[:30]
    password = str(data.get("password", ""))
    if not name or not login or not password:
        return jsonify({"error": "Заполните все поля"}), 400
    if len(password) < 4:
        return jsonify({"error": "Пароль слишком короткий (минимум 4 символа)"}), 400
    if find_user(login):
        return jsonify({"error": "Данный логин занят"}), 400
    with lock:
        users = load_users()
        user = {
            "id": max([u["id"] for u in users], default=0) + 1,
            "login": login,
            "name": name,
            "password": generate_password_hash(password),
            "is_admin": len(users) == 0,
            "blocked": [],
            "hidden": [],
        }
        users.append(user)
        save_users(users)
    session["login"] = login
    last_seen[login] = time.time()
    return jsonify({"ok": True, "login": login, "name": name, "is_admin": user["is_admin"]})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip()[:30]
    password = str(data.get("password", ""))
    user = find_user(login)
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Неверный логин или пароль"}), 400
    session["login"] = user["login"]
    last_seen[user["login"]] = time.time()
    return jsonify({"ok": True, "login": user["login"], "name": user["name"], "is_admin": user.get("is_admin", False)})


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
        "blocked": user.get("blocked", []),
        "hidden": user.get("hidden", []),
    })


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
        result.append({
            "login": u["login"],
            "name": u["name"],
            "online": is_online(u["login"]),
            "is_admin": u.get("is_admin", False),
            "iBlocked": u["login"].lower() in blocked_me,
            "blockedBy": False,
            "hidden": u["login"].lower() in hidden_me,
        })
    # заблокированный пользователь помечается и со стороны
    for item in result:
        target = find_user(item["login"])
        if target and me_user["login"].lower() in [b.lower() for b in target.get("blocked", [])]:
            item["blockedBy"] = True
    return jsonify(result)


@app.route("/api/messages", methods=["GET"])
def get_messages():
    user = current_user()
    if not user:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch(user)
    chat = request.args.get("chat", "public")
    after = request.args.get("after", default=0, type=int)
    with lock:
        msgs = load_messages()
        if chat == "public":
            blocked = [b.lower() for b in user.get("blocked", [])]
            result = [m for m in msgs if m["chat"] == "public" and m["id"] > after and m["login"].lower() not in blocked]
        else:
            with_ = request.args.get("with", "").strip()
            if not with_:
                return jsonify({"error": "Укажите собеседника"}), 400
            if not find_user(with_):
                return jsonify({"error": "Пользователь не найден"}), 404
            key = chat_key(user["login"], with_)
            result = [m for m in msgs if m["chat"] == key and m["id"] > after]
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
    if chat != "public":
        to = str(data.get("to", "")).strip()
        target = find_user(to)
        if not target:
            return jsonify({"error": "Пользователь не найден"}), 404
        if target["login"].lower() in [b.lower() for b in user.get("blocked", [])]:
            return jsonify({"error": "Вы заблокировали этого пользователя"}), 403
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
            "text": text,
            "time": int(time.time()),
        }
        msgs.append(msg)
        save_messages(msgs)
        return jsonify(msg)


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


# ---------- Admin ----------

@app.route("/api/admin/status")
def admin_status():
    user = current_admin()
    if not user:
        return jsonify({"is_admin": False, "unlocked": False})
    return jsonify({"is_admin": True, "unlocked": bool(session.get("admin_panel"))})


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    user = current_admin()
    if not user:
        return jsonify({"error": "Нет прав администратора"}), 403
    data = request.get_json(silent=True) or {}
    if str(data.get("password", "")) != ADMIN_PASSWORD:
        return jsonify({"error": "Неверный пароль"}), 403
    session["admin_panel"] = True
    return jsonify({"ok": True})


@app.route("/api/admin/users")
def admin_users():
    _, err = require_admin()
    if err:
        return err
    result = []
    for u in load_users():
        result.append({
            "login": u["login"],
            "name": u["name"],
            "is_admin": u.get("is_admin", False),
            "online": is_online(u["login"]),
            "blocked_count": len(u.get("blocked", [])),
            "hidden_count": len(u.get("hidden", [])),
        })
    result.sort(key=lambda x: (not x["is_admin"], x["login"].lower()))
    return jsonify(result)


@app.route("/api/admin/promote", methods=["POST"])
def admin_promote():
    admin, err = require_admin()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    if not login:
        return jsonify({"error": "Укажите логин"}), 400
    with lock:
        users = load_users()
        found = False
        for u in users:
            if u["login"].lower() == login:
                u["is_admin"] = True
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
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    if login == admin["login"].lower():
        return jsonify({"error": "Нельзя разжаловать самого себя"}), 400
    with lock:
        users = load_users()
        found = False
        for u in users:
            if u["login"].lower() == login:
                u["is_admin"] = False
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
    data = request.get_json(silent=True) or {}
    login = str(data.get("login", "")).strip().lower()
    if login == admin["login"].lower():
        return jsonify({"error": "Нельзя удалить самого себя"}), 400
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

        last_seen.pop(login, None)
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
