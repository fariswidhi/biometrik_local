# Biometrik Local

Layanan lokal (Flask, port 5000) yang membuka aplikasi BPJS Frista / Sidik Jari,
login otomatis, dan mengisi no kartu. Endpoint sama dengan yang dipanggil
`openFace()` dan `openFingerprint()` di `resources/views/checkin2.blade.php`.

Pengganti `autobiometrik.exe` (dimasnurpanca/autobiometrik), ditulis ulang dari hasil
analisis statis. Verifikasi biometrik tetap dilakukan di aplikasi BPJS.

## Pasang (PC anjungan, Windows)

    pip install -r requirements.txt
    python app.py          # pertama kali: jendela Pengaturan muncul, config.json dibuat otomatis

`pyautoit` memerlukan `AutoItX3` (terpasang bersama AutoIt, atau salin `AutoItX3_x64.dll`).

## Endpoint

| Endpoint | Fungsi |
|---|---|
| `GET /run_exe?no_peserta=` | Frista (wajah) |
| `GET /run_finger_exe?no_peserta=` | Sidik jari |
| `GET /stop_exe`, `GET /stop_finger_exe` | Tutup aplikasi |

## Keamanan
- Bind hanya `127.0.0.1`, CORS dibatasi ke `allowed_origins`.
- `no_peserta` harus 10-20 digit (tidak bisa dipakai menyuntik keystroke lain).
- `config.json` menyimpan password teks biasa: batasi akses folder ini di PC anjungan.

## Build jadi exe

    pip install pyinstaller pystray pillow
    python -m PyInstaller --onefile --noconsole --name biometrik-local --collect-all autoit app.py

Hasil: `dist\biometrik-local.exe`. Salin ke PC anjungan bersama `config.json`
(di folder yang sama dengan exe). Exe berjalan di system tray (klik kanan > Keluar),
log ada di `biometrik.log` di sebelah exe. Jalankan `python app.py --no-tray` untuk
mode konsol saat debugging.

Agar jalan otomatis saat Windows menyala: taruh shortcut exe di `shell:startup`.

## Pengaturan lewat UI

Klik kanan ikon tray > **Pengaturan...** (atau klik dua kali ikon), atau jalankan
`biometrik-local.exe --settings`. Di jendela itu bisa memilih path Frista dan After.exe
(tombol Pilih...) serta mengisi username/password. Disimpan ke `config.json` dan langsung
dipakai tanpa restart. Saat pertama kali dibuka tanpa `config.json`, jendela ini muncul otomatis.
`allowed_origins` hanya bisa diubah lewat `config.json` (berlaku setelah aplikasi dibuka ulang).

## Username & password dari web anjungan

Isi **Host web anjungan** di jendela Pengaturan (host saja, path API ditambahkan otomatis), misalnya
`anjungan-rsud-pati.test` atau `http://192.168.10.5:8000` (tombol **Tes** untuk mencoba).
Username/password lalu diambil dari web setiap kali Frista/Sidik Jari dibuka, jadi cukup
diubah sekali di halaman **Pengaturan Biometrik** pada web anjungan. Kalau API tidak bisa
dihubungi, dipakai username/password cadangan di `config.json`.

API ini tanpa token. Batasi dengan kolom "IP yang boleh mengambil kredensial" di halaman web.
