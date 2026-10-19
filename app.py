"""
Layanan lokal biometrik BPJS untuk anjungan (pengganti autobiometrik.exe).

Endpoint (kompatibel dengan openFace/openFingerprint di checkin2.blade.php):
  GET /run_exe?no_peserta=...          buka Frista (wajah), login, isi no kartu
  GET /run_finger_exe?no_peserta=...   buka aplikasi Sidik Jari BPJS, login, isi no kartu
  GET /stop_exe                        tutup frista.exe
  GET /stop_finger_exe                 tutup After.exe

Hanya mengotomasi UI aplikasi resmi BPJS (buka, login, isi no kartu).
Verifikasi biometriknya tetap dilakukan di aplikasi BPJS itu sendiri.
"""
import ctypes
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from ctypes import wintypes

import autoit
from flask import Flask, jsonify, request
from flask_cors import CORS

# Saat dibungkus exe (PyInstaller), config.json dibaca dari folder tempat exe berada
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def show_message(text, icon=0x40):
    """Kotak pesan Windows (0x40 info, 0x10 error). Dipakai karena exe tanpa konsol."""
    ctypes.windll.user32.MessageBoxW(0, text, "Biometrik Local", icon | 0x40000)


CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
except (OSError, ValueError) as e:
    show_message("config.json tidak bisa dibaca:\n%s\n\n%s" % (CONFIG_PATH, e), 0x10)
    sys.exit(1)

# Cegah dua salinan berjalan bersamaan (port 5000 hanya bisa dipakai satu)
_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\BiometrikLocalSingleInstance")
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    show_message("Biometrik Local sudah berjalan.\nCari ikonnya di system tray (klik panah ^ di dekat jam).")
    sys.exit(0)

FRISTA_PATH = config["path"]
FINGER_PATH = config["pathfinger"]
USERNAME = config["username"]
PASSWORD = config["password"]

FRISTA_LOGIN_TITLE = "Login Frista (Face Recognition BPJS Kesehatan)"
FRISTA_MAIN_TITLE = "Frista (Face Recognition BPJS Kesehatan) 3.0.2"
FINGER_TITLE = "Aplikasi Registrasi Sidik Jari"

app = Flask(__name__)
# Hanya halaman anjungan yang boleh memanggil layanan ini dari browser
CORS(app, origins=config.get("allowed_origins", ["http://anjungan-rsud-pati.test"]))
# Tanpa konsol (exe), log ditulis ke biometrik.log di sebelah exe
logging.basicConfig(
    level=logging.INFO,
    filename=os.path.join(BASE_DIR, "biometrik.log") if getattr(sys, "frozen", False) else None,
)

user32 = ctypes.windll.user32
user32.BlockInput.argtypes = [wintypes.BOOL]
user32.BlockInput.restype = wintypes.BOOL

# Satu otomasi UI pada satu waktu, supaya keystroke tidak bercampur
ui_lock = threading.Lock()


def sel(title):
    return "[TITLE:%s]" % title


def kill_process(name):
    subprocess.call(["taskkill", "/f", "/im", name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_finger(no_peserta):
    with ui_lock:
        try:
            autoit.run(FINGER_PATH)
            if not autoit.win_wait_active(sel(FINGER_TITLE), 10):
                logging.error("Window '%s' tidak muncul dalam 10 detik", FINGER_TITLE)
                return
            autoit.win_activate(sel(FINGER_TITLE))
            autoit.win_set_on_top(sel(FINGER_TITLE), 1)

            user32.BlockInput(True)
            try:
                autoit.control_send(sel(FINGER_TITLE), "", USERNAME, 1)
                autoit.control_send(sel(FINGER_TITLE), "", "{TAB}")
                time.sleep(0.5)
                autoit.control_send(sel(FINGER_TITLE), "", PASSWORD, 1)
                autoit.control_send(sel(FINGER_TITLE), "", "{TAB}")
                autoit.control_send(sel(FINGER_TITLE), "", "{SPACE}")
            finally:
                user32.BlockInput(False)

            time.sleep(3)  # tunggu form utama setelah login
            autoit.control_send(sel(FINGER_TITLE), "", no_peserta, 1)
            logging.info("No kartu %s dikirim ke %s", no_peserta, FINGER_TITLE)
        except Exception as e:
            logging.error("Error run_finger: %s", e)


def run_frista(no_peserta):
    with ui_lock:
        try:
            autoit.run(FRISTA_PATH)
            autoit.win_wait(sel(FRISTA_LOGIN_TITLE), 10)
            autoit.win_activate(sel(FRISTA_LOGIN_TITLE))
            autoit.win_set_on_top(sel(FRISTA_LOGIN_TITLE), 1)

            user32.BlockInput(True)
            try:
                autoit.control_focus(sel(FRISTA_LOGIN_TITLE), "TkChild4")
                autoit.control_send(sel(FRISTA_LOGIN_TITLE), "TkChild4", USERNAME, 1)
                autoit.control_send(sel(FRISTA_LOGIN_TITLE), "TkChild4", "{TAB}")
                time.sleep(0.5)
                autoit.control_focus(sel(FRISTA_LOGIN_TITLE), "TkChild3")
                autoit.control_send(sel(FRISTA_LOGIN_TITLE), "TkChild3", PASSWORD, 1)
                autoit.control_send(sel(FRISTA_LOGIN_TITLE), "TkChild3", "{TAB}")
                autoit.control_send(sel(FRISTA_LOGIN_TITLE), "Button1", "{SPACE}")
                time.sleep(1)  # tunggu jendela utama Frista

                autoit.win_activate(sel(FRISTA_MAIN_TITLE))
                autoit.win_set_on_top(sel(FRISTA_MAIN_TITLE), 1)
                autoit.control_focus(FRISTA_MAIN_TITLE, "TkChild2")
                autoit.control_send(FRISTA_MAIN_TITLE, "TkChild2", no_peserta, 1)
            finally:
                user32.BlockInput(False)
            logging.info("No kartu %s dikirim ke Frista", no_peserta)
        except Exception as e:
            logging.error("Error run_frista: %s", e)


def get_no_peserta():
    """No kartu BPJS = 13 digit. Hanya angka agar tidak bisa dipakai menyuntik keystroke."""
    no = request.args.get("no_peserta", "", type=str).strip()
    if not re.fullmatch(r"\d{10,20}", no):
        return None
    return no


def start(target, process_name, no_peserta):
    kill_process(process_name)  # pastikan tidak ada instance lama
    threading.Thread(target=target, args=(no_peserta,), daemon=True).start()
    return jsonify(status="running", message="Process started successfully"), 200


@app.route("/run_exe", methods=["GET"])
def run_exe_endpoint():
    no = get_no_peserta()
    if not no:
        return jsonify(status="error", message="Parameter no_peserta tidak valid"), 400
    return start(run_frista, "frista.exe", no)


@app.route("/run_finger_exe", methods=["GET"])
def run_finger_endpoint():
    no = get_no_peserta()
    if not no:
        return jsonify(status="error", message="Parameter no_peserta tidak valid"), 400
    return start(run_finger, "After.exe", no)


def stop(process_name):
    out = subprocess.run(["taskkill", "/f", "/im", process_name],
                         capture_output=True, text=True)
    if out.returncode == 0:
        return jsonify(message="Process %s has been terminated." % process_name), 200
    return jsonify(message="%s not found." % process_name), 404


@app.route("/stop_exe", methods=["GET"])
def stop_exe():
    return stop("frista.exe")


@app.route("/stop_finger_exe", methods=["GET"])
def stop_finger_exe():
    return stop("After.exe")


def run_server():
    # 127.0.0.1 saja: tidak boleh bisa diakses dari jaringan
    app.run(host="127.0.0.1", port=5000, debug=False)


def run_tray():
    """Jalankan server di thread terpisah dan tampilkan icon di system tray."""
    import pystray
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (64, 64), "#198754")
    ImageDraw.Draw(img).ellipse((16, 16, 48, 48), fill="white")

    def keluar(icon, item):
        icon.stop()
        os._exit(0)

    threading.Thread(target=run_server, daemon=True).start()
    # Tampilkan pesan di thread terpisah agar tidak menahan icon tray
    threading.Thread(
        target=show_message,
        args=("Biometrik Local aktif di port 5000.\nAplikasi berjalan di system tray "
              "(klik panah ^ di dekat jam, klik kanan ikon > Keluar untuk menutup).",),
        daemon=True,
    ).start()
    menu =pystray.Menu(
        pystray.MenuItem("Biometrik Local (port 5000)", None, enabled=False),
        pystray.MenuItem("Keluar", keluar),
    )
    pystray.Icon("biometrik-local", img, "Biometrik Local", menu).run()


if __name__ == "__main__":
    if "--no-tray" in sys.argv:
        run_server()
    else:
        run_tray()
