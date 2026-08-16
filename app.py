import time
from threading import Lock

from flask import Flask, jsonify, render_template, request, session

app = Flask(__name__)
app.secret_key = "messenger-secret-key-change-me"

messages = []
lock = Lock()
next_id = 1
MAX_MESSAGES = 500


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/me", methods=["GET", "POST"])
def me():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()[:30]
        if name:
            session["name"] = name
    return jsonify({"name": session.get("name", "")})


@app.route("/api/messages", methods=["GET"])
def get_messages():
    after = request.args.get("after", default=0, type=int)
    with lock:
        return jsonify([m for m in messages if m["id"] > after])


@app.route("/api/messages", methods=["POST"])
def post_message():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or session.get("name") or "Аноним").strip()[:30]
    text = str(data.get("text") or "").strip()[:1000]
    if not text:
        return jsonify({"error": "Сообщение не может быть пустым"}), 400

    global next_id
    with lock:
        msg = {
            "id": next_id,
            "name": name,
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
