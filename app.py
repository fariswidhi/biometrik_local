"""
Layanan lokal biometrik BPJS untuk anjungan (pengganti autobiometrik.exe).

Endpoint (kompatibel dengan openFace/openFingerprint di checkin2.blade.php):
  GET /run_exe?no_peserta=...          buka Frista (wajah), login, isi no kartu
  GET /run_finger_exe?no_peserta=...   buka aplikasi Sidik Jari BPJS, login, isi no kartu
  GET /stop_exe                        tutup frista.exe
  GET /stop_finger_exe                 tutup After.exe

Hanya mengotomasi UI aplikasi resmi BPJS (buka, login, isi no kartu).
Verifikasi biometriknya tetap dilakukan di aplikasi BPJS itu sendiri.

Pengaturan (path aplikasi, host web anjungan) diubah lewat jendela Pengaturan
(menu tray > Pengaturan, atau `app.py --settings`) dan disimpan di config.json.
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
FROZEN = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULTS = {
    "path": r"C:\frista\frista.exe",
    "pathfinger": r"C:\Program Files (x86)\BPJS Kesehatan\Aplikasi Sidik Jari BPJS Kesehatan\After.exe",
    # Host web anjungan; username/password BPJS 100% diambil dari API-nya, tidak disimpan di sini
    "credentials_url": "http://10.0.108.249:82/",
    "allowed_origins": ["http://anjungan-rsud-pati.test"],
}


def show_message(text, icon=0x40):
    """Kotak pesan Windows (0x40 info, 0x10 error). Dipakai karena exe tanpa konsol."""
    ctypes.windll.user32.MessageBoxW(0, text, "Biometrik Local", icon | 0x40000)


def load_config():
    """Baca config.json setiap dipakai, supaya perubahan dari jendela Pengaturan langsung berlaku."""
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    # Host kosong di config.json dianggap belum diatur: pakai host bawaan
    if not str(cfg.get("credentials_url", "")).strip():
        cfg["credentials_url"] = DEFAULTS["credentials_url"]
    return cfg


CREDENTIALS_PATH = "/api/biometrik/credentials"


def credentials_endpoint(host):
    """Cukup isi host web anjungan (mis. anjungan-rsud-pati.test atau http://192.168.10.5:8000).
    Skema http:// ditambahkan kalau tidak ada, dan path API ditambahkan otomatis."""
    host = host.strip().rstrip("/")
    if not host.lower().startswith(("http://", "https://")):
        host = "http://" + host
    if not host.endswith(CREDENTIALS_PATH):
        host += CREDENTIALS_PATH
    return host


def fetch_credentials(host, timeout=5):
    """Ambil {'username','password'} dari API web anjungan. Raise kalau gagal."""
    import urllib.request

    url = credentials_endpoint(host)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("username") or not data.get("password"):
        raise ValueError("Respon API tidak berisi username/password")
    return data["username"], data["password"]


def get_credentials(cfg):
    """Selalu dari API web anjungan. Raise kalau host belum diisi atau API gagal."""
    if not cfg.get("credentials_url"):
        raise ValueError("Host web anjungan belum diatur (menu tray > Pengaturan)")
    return fetch_credentials(cfg["credentials_url"])


def save_config(values):
    cfg = load_config()
    cfg.update(values)
    # Buang username/password lama dari versi sebelumnya agar tidak tersisa di disk
    cfg.pop("username", None)
    cfg.pop("password", None)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "BiometrikLocal"


def is_autostart():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return bool(winreg.QueryValueEx(k, RUN_NAME)[0])
    except OSError:
        return False


def set_autostart(enabled):
    """Daftarkan/hapus exe di HKCU\\...\\Run (tanpa hak administrator, aktif saat user login)."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, '"%s"' % sys.executable)
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


def settings_window():
    """Jendela pengaturan. Mengembalikan True kalau disimpan."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    cfg = load_config()
    saved = {"ok": False}

    root = tk.Tk()
    root.title("Biometrik Local - Pengaturan")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    frm = ttk.Frame(root, padding=16)
    frm.grid()

    vars_ = {
        "path": tk.StringVar(value=cfg["path"]),
        "pathfinger": tk.StringVar(value=cfg["pathfinger"]),
        "credentials_url": tk.StringVar(value=cfg["credentials_url"]),
    }

    def browse(key):
        f = filedialog.askopenfilename(
            parent=root, title="Pilih aplikasi",
            filetypes=[("Aplikasi", "*.exe"), ("Semua file", "*.*")],
            initialdir=os.path.dirname(vars_[key].get()) or None)
        if f:
            vars_[key].set(os.path.normpath(f))

    ttk.Label(frm, text="Aplikasi BPJS", font=("Segoe UI", 11, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
    rows = [("Frista (wajah)", "path"), ("Sidik jari (After.exe)", "pathfinger")]
    for i, (label, key) in enumerate(rows, start=1):
        ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=3)
        ttk.Entry(frm, textvariable=vars_[key], width=60).grid(row=i, column=1, padx=6)
        ttk.Button(frm, text="Pilih...", command=lambda k=key: browse(k)).grid(row=i, column=2)

    ttk.Label(frm, text="Akun login BPJS (diambil dari web anjungan)", font=("Segoe UI", 11, "bold")).grid(
        row=3, column=0, columnspan=3, sticky="w", pady=(12, 6))
    ttk.Label(frm, text="Host web anjungan").grid(row=6, column=0, sticky="w", pady=3)
    ttk.Entry(frm, textvariable=vars_["credentials_url"], width=60).grid(row=6, column=1, padx=6, pady=3)

    def tes_api():
        url = vars_["credentials_url"].get().strip()
        if not url:
            messagebox.showwarning("Host kosong", "Isi host web anjungan dulu.", parent=root)
            return
        try:
            user, _ = fetch_credentials(url)
            messagebox.showinfo("Berhasil", "API merespons. Username dari server: %s" % user, parent=root)
        except Exception as e:
            messagebox.showerror("Gagal", "Tidak bisa mengambil kredensial:\n%s" % e, parent=root)

    ttk.Button(frm, text="Tes", command=tes_api).grid(row=6, column=2, pady=3)
    ttk.Label(frm, foreground="#666", justify="left",
              text="Isi host saja, mis. anjungan-rsud-pati.test atau http://192.168.10.5:8000 (tanpa path API).\n"
                   "Username/password tidak disimpan di PC ini; diambil dari web anjungan setiap kali dipakai\n"
                   "(diatur di halaman Pengaturan Biometrik pada web anjungan).").grid(
        row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))

    # Jalan otomatis saat Windows menyala: hanya untuk exe (bukan `python app.py`).
    # Default aktif saat pertama kali dipasang (config.json belum ada).
    autostart_var = tk.BooleanVar(value=is_autostart() or not os.path.isfile(CONFIG_PATH))
    chk = ttk.Checkbutton(frm, text="Jalankan otomatis saat Windows menyala", variable=autostart_var)
    chk.grid(row=8, column=0, columnspan=3, sticky="w", pady=(10, 0))
    if not FROZEN:
        autostart_var.set(False)
        chk.state(["disabled"])

    def simpan():
        values = {k: v.get().strip() for k, v in vars_.items()}
        if not values["credentials_url"]:
            messagebox.showwarning("Host kosong", "Host web anjungan wajib diisi.", parent=root)
            return
        missing = [n for k, n in (("path", "Frista"), ("pathfinger", "Sidik jari"))
                   if values[k] and not os.path.isfile(values[k])]
        if missing and not messagebox.askyesno(
                "File tidak ditemukan",
                "File aplikasi %s tidak ditemukan.\nTetap simpan?" % ", ".join(missing), parent=root):
            return
        try:
            save_config(values)
        except OSError as e:
            messagebox.showerror("Gagal menyimpan", "%s\n\n%s" % (CONFIG_PATH, e), parent=root)
            return
        if FROZEN:
            try:
                set_autostart(autostart_var.get())
            except OSError as e:
                messagebox.showerror("Gagal mengatur auto-start", str(e), parent=root)
        saved["ok"] = True
        messagebox.showinfo("Tersimpan", "Pengaturan disimpan dan langsung dipakai.", parent=root)
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=9, column=0, columnspan=3, sticky="e", pady=(14, 0))
    ttk.Button(btns, text="Batal", command=root.destroy).grid(row=0, column=0, padx=6)
    ttk.Button(btns, text="Simpan", command=simpan).grid(row=0, column=1)

    root.mainloop()
    return saved["ok"]


def open_settings_process():
    """Buka jendela pengaturan di proses terpisah (tidak mengganggu icon tray)."""
    cmd = [sys.executable, "--settings"] if FROZEN else [sys.executable, os.path.abspath(__file__), "--settings"]
    subprocess.Popen(cmd)


# Mode jendela pengaturan saja: tidak ada server, tidak kena batas satu salinan
if "--settings" in sys.argv:
    settings_window()
    sys.exit(0)

# Pertama kali dijalankan (config.json belum ada): minta pengaturan dulu
if not os.path.isfile(CONFIG_PATH):
    show_message("Selamat datang. Atur dulu path aplikasi BPJS dan akun login.")
    if not settings_window():
        sys.exit(0)

# Cegah dua salinan berjalan bersamaan (port 5000 hanya bisa dipakai satu)
_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\BiometrikLocalSingleInstance")
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    show_message("Biometrik Local sudah berjalan.\nCari ikonnya di system tray (klik panah ^ di dekat jam).")
    sys.exit(0)

FRISTA_LOGIN_TITLE = "Login Frista (Face Recognition BPJS Kesehatan)"
FRISTA_MAIN_TITLE = "Frista (Face Recognition BPJS Kesehatan) 3.0.2"
FINGER_TITLE = "Aplikasi Registrasi Sidik Jari"

app = Flask(__name__)
# Hanya halaman anjungan yang boleh memanggil layanan ini dari browser
# (perubahan allowed_origins di config.json berlaku setelah aplikasi dibuka ulang)
CORS(app, origins=load_config()["allowed_origins"])
# Tanpa konsol (exe), log ditulis ke biometrik.log di sebelah exe
logging.basicConfig(
    level=logging.INFO,
    filename=os.path.join(BASE_DIR, "biometrik.log") if FROZEN else None,
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
            cfg = load_config()
            username, password = get_credentials(cfg)
            autoit.run(cfg["pathfinger"])
            if not autoit.win_wait_active(sel(FINGER_TITLE), 10):
                logging.error("Window '%s' tidak muncul dalam 10 detik", FINGER_TITLE)
                return
            autoit.win_activate(sel(FINGER_TITLE))
            autoit.win_set_on_top(sel(FINGER_TITLE), 1)

            user32.BlockInput(True)
            try:
                autoit.control_send(sel(FINGER_TITLE), "", username, 1)
                autoit.control_send(sel(FINGER_TITLE), "", "{TAB}")
                time.sleep(0.5)
                autoit.control_send(sel(FINGER_TITLE), "", password, 1)
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
            cfg = load_config()
            username, password = get_credentials(cfg)
            autoit.run(cfg["path"])
            autoit.win_wait(sel(FRISTA_LOGIN_TITLE), 10)
            autoit.win_activate(sel(FRISTA_LOGIN_TITLE))
            autoit.win_set_on_top(sel(FRISTA_LOGIN_TITLE), 1)

            user32.BlockInput(True)
            try:
                autoit.control_focus(sel(FRISTA_LOGIN_TITLE), "TkChild4")
                autoit.control_send(sel(FRISTA_LOGIN_TITLE), "TkChild4", username, 1)
                autoit.control_send(sel(FRISTA_LOGIN_TITLE), "TkChild4", "{TAB}")
                time.sleep(0.5)
                autoit.control_focus(sel(FRISTA_LOGIN_TITLE), "TkChild3")
                autoit.control_send(sel(FRISTA_LOGIN_TITLE), "TkChild3", password, 1)
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
              "(klik panah ^ di dekat jam, klik kanan ikon > Pengaturan / Keluar).",),
        daemon=True,
    ).start()
    menu = pystray.Menu(
        pystray.MenuItem("Biometrik Local (port 5000)", None, enabled=False),
        pystray.MenuItem("Pengaturan...", lambda icon, item: open_settings_process(), default=True),
        pystray.MenuItem("Keluar", keluar),
    )
    pystray.Icon("biometrik-local", img, "Biometrik Local", menu).run()


if __name__ == "__main__":
    if "--no-tray" in sys.argv:
        run_server()
    else:
        run_tray()
