import json
import os
import threading
import time

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(APP_DIR, "users.json")

app = Flask(__name__)
app.secret_key = "messenger-secret-key-change-me"

messages = []
lock = threading.Lock()
next_id = 1
MAX_MESSAGES = 500
ONLINE_TIMEOUT = 20

last_seen = {}


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
    login = login.strip().lower()
    for u in load_users():
        if u["login"].lower() == login:
            return u
    return None


def touch():
    login = session.get("login")
    if login:
        last_seen[login] = time.time()


def is_online(login):
    return time.time() - last_seen.get(login, 0) < ONLINE_TIMEOUT


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
    users = load_users()
    user = {
        "id": max([u["id"] for u in users], default=0) + 1,
        "login": login,
        "name": name,
        "password": generate_password_hash(password),
    }
    users.append(user)
    save_users(users)
    session["login"] = login
    last_seen[login] = time.time()
    return jsonify({"ok": True, "login": login, "name": name})


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
    return jsonify({"ok": True, "login": user["login"], "name": user["name"]})


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
    return jsonify({"authenticated": True, "login": user["login"], "name": user["name"]})


@app.route("/api/users")
def users():
    touch()
    result = []
    for u in load_users():
        result.append({
            "login": u["login"],
            "name": u["name"],
            "online": is_online(u["login"]),
        })
    return jsonify(result)


@app.route("/api/messages", methods=["GET"])
def get_messages():
    touch()
    after = request.args.get("after", default=0, type=int)
    with lock:
        return jsonify([m for m in messages if m["id"] > after])


@app.route("/api/messages", methods=["POST"])
def post_message():
    login = session.get("login")
    if not login:
        return jsonify({"error": "Войдите в аккаунт"}), 401
    touch()
    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()[:1000]
    if not text:
        return jsonify({"error": "Сообщение не может быть пустым"}), 400
    user = find_user(login)

    global next_id
    with lock:
        msg = {
            "id": next_id,
            "login": login,
            "name": user["name"],
            "text": text,
            "time": int(time.time()),
        }
        next_id += 1
        messages.append(msg)
        if len(messages) > MAX_MESSAGES:
            del messages[: len(messages) - MAX_MESSAGES]
        return jsonify(msg)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
