# Biometrik Local

Layanan lokal (Flask, port 5000) yang membuka aplikasi BPJS Frista / Sidik Jari,
login otomatis, dan mengisi no kartu. Endpoint sama dengan yang dipanggil
`openFace()` dan `openFingerprint()` di `resources/views/checkin2.blade.php`.

Pengganti `autobiometrik.exe` (dimasnurpanca/autobiometrik), ditulis ulang dari hasil
analisis statis. Verifikasi biometrik tetap dilakukan di aplikasi BPJS.

## Pasang (PC anjungan, Windows)

    pip install -r requirements.txt
    copy config.example.json config.json   # isi username & password, JANGAN di-commit
    python app.py

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
