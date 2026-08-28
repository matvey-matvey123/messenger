import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile

APP_TITLE = "Кокаколик"
if getattr(sys, "frozen", False):
    APP_DIR = sys._MEIPASS
    BASE_DIR = os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local"),
        "Кокаколик",
    )
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
try:
    os.makedirs(BASE_DIR, exist_ok=True)
except OSError:
    pass
CONFIG_FILE = os.path.join(BASE_DIR, "app_config.json")
BIN_DIR = os.path.join(BASE_DIR, "bin")
SING_BOX = os.path.join(BIN_DIR, "sing-box.exe")
SG_CONFIG = os.path.join(BASE_DIR, "sg_config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
SETTINGS_PAGE = os.path.join(APP_DIR, "settings.html")
PROXY_PORT = 2080
LOG_FILE = os.path.join(BASE_DIR, "desktop_error.log")

DEFAULT_SERVER = "https://matveymatveyg.pythonanywhere.com/"

VLESS_PRESETS = [
    {
        "id": "netherlands1",
        "name": "Нидерланды | 1 (бесплатный)",
        "link": "vless://f294108f-8fe9-4422-9837-69212a8fb4ec@freeshka.i-love-russia.online:443?encryption=none&flow=xtls-rprx-vision&security=reality&sni=freeshka.i-love-russia.online&fp=firefox&pbk=Tm50a8xPW6cazNhgmTSHNbVfqaplvNSx0BQoJCGe3jU&sid=4aa753c327e7fd94&type=tcp&headerType=none&host=freeshka.i-love-russia.online",
    },
]

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(message)s",
)


def log(msg):
    logging.error(msg)


def _already_running():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "KokacolikDesktopAppMutex")
    return ctypes.windll.kernel32.GetLastError() == 183, mutex


def _ensure_webview2_patch():
    frozen = bool(getattr(sys, "frozen", False))
    try:
        import importlib.util
        spec = importlib.util.find_spec("webview.platforms.edgechromium")
        if spec is None or not spec.origin:
            log("webview edgechromium not found")
            return
        path = os.path.abspath(spec.origin)
    except Exception as e:
        log("webview edgechromium not available: %s" % e)
        return
    if frozen:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    if "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS" in f.read():
                        return
            except OSError:
                pass
        return
    marker = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        log("cannot read webview patch file: %s" % e)
        return
    if marker in src:
        return
    anchor = "props.AdditionalBrowserArguments = '--disable-features=ElasticOverscroll'"
    if anchor not in src:
        log("webview patch anchor not found")
        return
    patch = (
        "\n"
        "        _extra = os.environ.get('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS')\n"
        "        if _extra:\n"
        "            props.AdditionalBrowserArguments += ' ' + _extra\n"
    )
    src = src.replace(anchor, anchor + patch, 1)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
    except OSError as e:
        log("cannot write webview patch: %s" % e)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------- VLESS parsing ----------

def parse_vless(link):
    u = urllib.parse.urlparse(link.strip())
    if u.scheme != "vless":
        return None
    hostport = u.netloc
    if "@" in hostport:
        uuid, hostport = hostport.rsplit("@", 1)
    else:
        uuid = ""
    if ":" in hostport:
        server, port = hostport.rsplit(":", 1)
        port = int(port)
    else:
        server, port = hostport, 443
    qs = urllib.parse.parse_qs(u.query)
    return {
        "uuid": uuid,
        "server": server,
        "port": port,
        "flow": (qs.get("flow") or [""])[0],
        "sni": (qs.get("sni") or [server])[0],
        "fp": (qs.get("fp") or ["firefox"])[0],
        "pbk": (qs.get("pbk") or [""])[0],
        "sid": (qs.get("sid") or [""])[0],
        "security": (qs.get("security") or ["reality"])[0],
    }


def make_sg_config(vless):
    outbound = {
        "type": "vless",
        "tag": "proxy",
        "server": vless["server"],
        "server_port": vless["port"],
        "uuid": vless["uuid"],
    }
    if vless["flow"]:
        outbound["flow"] = vless["flow"]
    tls = {"enabled": True, "server_name": vless["sni"]}
    utls = {"enabled": True, "fingerprint": vless["fp"]}
    if vless["security"] == "reality" and vless["pbk"]:
        reality = {"enabled": True, "public_key": vless["pbk"]}
        if vless["sid"]:
            reality["short_id"] = vless["sid"]
        tls["reality"] = reality
    tls["utls"] = utls
    outbound["tls"] = tls
    return {
        "log": {"level": "warn", "timestamp": True},
        "inbounds": [
            {"type": "socks", "tag": "socks-in", "listen": "127.0.0.1", "listen_port": PROXY_PORT}
        ],
        "outbounds": [
            {"type": "direct", "tag": "direct"},
            outbound,
        ],
        "route": {"final": "proxy"},
    }


# ---------- sing-box ----------

_singbox_proc = None
_last_vless = None
_stop_watchdog = False
_lock = threading.Lock()


def ensure_singbox():
    if os.path.exists(SING_BOX):
        return True, None
    log("sing-box not found, downloading...")
    try:
        os.makedirs(BIN_DIR, exist_ok=True)
        api_url = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
        with urllib.request.urlopen(api_url, timeout=20) as r:
            latest = json.loads(r.read())
        tag = latest["tag_name"]  # like v1.12.3
        version = tag.lstrip("v")
        asset = "sing-box-{0}-windows-amd64.zip".format(version)
        url = "https://github.com/SagerNet/sing-box/releases/download/{0}/{1}".format(tag, asset)
        tmp = os.path.join(BIN_DIR, "singbox.zip")
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        with zipfile.ZipFile(tmp, "r") as z:
            for name in z.namelist():
                if name.endswith("sing-box.exe"):
                    z.extract(name, BIN_DIR)
                    extracted = os.path.join(BIN_DIR, name)
                    shutil.move(extracted, SING_BOX)
                    break
        try:
            os.remove(tmp)
        except OSError:
            pass
        if not os.path.exists(SING_BOX):
            return False, "Не удалось найти sing-box.exe в архиве"
        return True, None
    except Exception as e:
        log("sing-box download failed: %s" % e)
        return False, "Не удалось скачать sing-box: {0}".format(e)


def _spawn_singbox(vless):
    global _singbox_proc
    cfg = make_sg_config(vless)
    with open(SG_CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    create = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    _singbox_proc = subprocess.Popen(
        [SING_BOX, "run", "-c", SG_CONFIG],
        cwd=BASE_DIR,
        creationflags=create,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.5)
    return None


def _watchdog():
    while not _stop_watchdog:
        time.sleep(5)
        if _stop_watchdog:
            break
        try:
            if _singbox_proc is not None and _singbox_proc.poll() is not None:
                log("sing-box exited with code %s, restarting..." % _singbox_proc.poll())
                if _last_vless:
                    _spawn_singbox(_last_vless)
        except Exception as e:
            log("watchdog error: %s" % e)


def start_proxy(vless):
    global _last_vless, _stop_watchdog
    ok, err = ensure_singbox()
    if not ok:
        return err
    _last_vless = vless
    err = _spawn_singbox(vless)
    if err:
        return err
    if not _singbox_proc or _singbox_proc.poll() is not None:
        return "Не удалось запустить sing-box"
    if not _stop_watchdog:
        _stop_watchdog = False
        threading.Thread(target=_watchdog, daemon=True).start()
    return None


def stop_proxy():
    global _singbox_proc, _stop_watchdog
    _stop_watchdog = True
    if _singbox_proc:
        try:
            _singbox_proc.terminate()
        except Exception:
            pass
        _singbox_proc = None


def _restart_app():
    time.sleep(1.5)
    stop_proxy()
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        sibling = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(sibling):
            exe = sibling
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen([exe, os.path.abspath(__file__)], cwd=BASE_DIR, creationflags=flags)
    os._exit(0)


def find_preset(proxy_id):
    for p in VLESS_PRESETS:
        if p["id"] == proxy_id:
            return p
    return None


# ---------- JS API ----------

class Api:
    def get_state(self):
        cfg = load_config()
        proxies = [{"id": "", "name": "Без прокси"}]
        proxies += [{"id": p["id"], "name": p["name"]} for p in VLESS_PRESETS]
        proxy_status = "sing-box: %s" % ("готов" if os.path.exists(SING_BOX) else "не скачан (скачается при первом подключении)")
        return {
            "has_config": bool(cfg.get("server")),
            "server": cfg.get("server") or DEFAULT_SERVER,
            "proxy_id": cfg.get("proxy_id", ""),
            "proxies": proxies,
            "proxy_status": proxy_status,
        }

    def save_and_connect(self, server, proxy_id):
        save_config({"server": server, "proxy_id": proxy_id})
        threading.Thread(target=_restart_app, daemon=True).start()
        return {"ok": True}


def _watch_page(window, url):
    """If the page fails to load (free proxy blips), keep reloading until it opens."""
    while True:
        time.sleep(4)
        try:
            js = "document.location.protocol + '|' + document.readyState"
            proto, state = (window.evaluate_js(js) or "||").split("|")[:2]
        except Exception:
            proto, state = None, None
        if proto == "file:":
            continue
        if proto and proto.startswith("https"):
            continue
        if state == "loading" or state == "interactive":
            continue
        try:
            window.load_url(url)
        except Exception:
            pass


# ---------- Main ----------

def main():
    running, mutex = _already_running()
    if running:
        ctypes.windll.user32.MessageBoxW(None, "Кокаколик уже запущен!", APP_TITLE, 0x40)
        return

    import webview

    _ensure_webview2_patch()

    cfg = load_config()
    if not cfg.get("server"):
        cfg = {"server": DEFAULT_SERVER, "proxy_id": "netherlands1"}
        save_config(cfg)
    if cfg.get("proxy_id"):
        preset = find_preset(cfg["proxy_id"])
        if preset:
            err = start_proxy(parse_vless(preset["link"]))
            if err:
                ctypes.windll.user32.MessageBoxW(None, "Ошибка прокси:\n" + err, APP_TITLE, 0x10)
    if cfg.get("proxy_id"):
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            "--proxy-server=socks5://127.0.0.1:{0} --proxy-bypass-list=<-loopback>".format(PROXY_PORT)
        )
    url = cfg.get("server") or ("file:///" + SETTINGS_PAGE.replace("\\", "/"))

    api = Api()
    _ = api
    window = webview.create_window(
        APP_TITLE,
        url,
        width=1280,
        height=800,
        min_size=(900, 600),
        background_color="#1a1a2e",
        js_api=api,
    )

    try:
        from webview.menu import Menu, MenuAction
        menu = [
            Menu("Кокаколик", [
                MenuAction("Настройки сервера", lambda w: w.load_url("file:///" + SETTINGS_PAGE.replace("\\", "/"))),
            ])
        ]
    except Exception:
        menu = []

    try:
        if url.startswith("http"):
            threading.Thread(target=_watch_page, args=(window, url), daemon=True).start()
        webview.start(
            debug=False,
            http_server=False,
            menu=menu,
            private_mode=False,
            storage_path=DATA_DIR,
        )
    except Exception as e:
        log("webview failed: %s" % e)
        ctypes.windll.user32.MessageBoxW(None, "Ошибка запуска:\n" + str(e), APP_TITLE, 0x10)
    finally:
        stop_proxy()
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()