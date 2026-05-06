# 📹 CCTV File-Based Monitoring System

Sistem monitoring CCTV otomatis berbasis Python yang mendeteksi kamera yang tidak mengirim
file gambar lebih dari batas waktu yang ditentukan, dan mengirimkan notifikasi via Telegram.

---

## 📁 Struktur Project

```
cctv_monitor/
├── monitor.py          # Program utama
├── config.py           # Semua konfigurasi (edit ini dulu!)
├── test_setup.py       # Tes koneksi sebelum deploy
├── requirements.txt    # Library yang dibutuhkan
├── logs/
│   └── monitoring.log  # Log otomatis dibuat di sini
└── state/
    └── camera_states.json  # State anti-spam (auto dibuat)
```

---

## ⚡ Cara Cepat Mulai

### Langkah 1 — Install Python & library

```bash
# Pastikan Python 3.10+ terinstall
python --version

# Install library yang dibutuhkan
pip install -r requirements.txt
```

### Langkah 2 — Dapatkan Token & Chat ID Telegram

1. Buka Telegram, cari **@BotFather**
2. Ketik `/newbot` → ikuti instruksi → copy token yang diberikan
3. Kirim pesan ke bot kamu (wajib dilakukan minimal 1x)
4. Buka URL ini di browser (ganti TOKEN):
   ```
   https://api.telegram.org/botTOKEN/getUpdates
   ```
5. Cari `"chat":{"id": ANGKA_INI}` → itu adalah Chat ID kamu

### Langkah 3 — Edit config.py

Buka `config.py` dan sesuaikan:

```python
CCTV_CAMERAS = {
    "Lobby Depan" : "/nas/cctv/cam1",   # Ganti dengan path asli
    "Parkiran"    : "/nas/cctv/cam2",
}

TELEGRAM_BOT_TOKEN = "1234567890:ABCdef..."   # Token dari BotFather
TELEGRAM_CHAT_ID   = "-1001234567890"          # Chat ID kamu
```

### Langkah 4 — Tes dulu sebelum deploy

```bash
python test_setup.py
```

Jika berhasil, kamu akan menerima pesan Telegram konfirmasi. ✅

### Langkah 5 — Jalankan monitor

```bash
python monitor.py
```

---

## 🐧 Deployment di Linux (Cron)

Gunakan cron agar sistem berjalan otomatis saat reboot.

```bash
# Edit crontab
crontab -e
```

Tambahkan baris ini di bagian bawah:

```cron
# Jalankan CCTV monitor saat boot, restart otomatis jika crash
@reboot /usr/bin/python3 /path/to/cctv_monitor/monitor.py >> /path/to/cctv_monitor/logs/cron.log 2>&1
```

Atau jika ingin dijalankan via systemd (lebih robust):

**Buat file service:**

```bash
sudo nano /etc/systemd/system/cctv-monitor.service
```

**Isi file service:**

```ini
[Unit]
Description=CCTV File Monitor
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/cctv_monitor
ExecStart=/usr/bin/python3 /path/to/cctv_monitor/monitor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Aktifkan service:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable cctv-monitor
sudo systemctl start cctv-monitor

# Cek status
sudo systemctl status cctv-monitor

# Lihat log real-time
sudo journalctl -u cctv-monitor -f
```

---

## 🪟 Deployment di Windows (Task Scheduler)

### Cara via GUI:

1. Buka **Task Scheduler** (cari di Start Menu)
2. Klik **"Create Basic Task"**
3. Name: `CCTV Monitor`
4. Trigger: **"When the computer starts"**
5. Action: **"Start a program"**
6. Program: `C:\Python311\python.exe`
7. Arguments: `C:\path\to\cctv_monitor\monitor.py`
8. Start in: `C:\path\to\cctv_monitor\`
9. Klik Finish ✅

### Cara via Command Prompt (admin):

```cmd
schtasks /create /tn "CCTV Monitor" /tr "python C:\path\to\monitor.py" /sc onstart /ru SYSTEM
```

---

## 🔧 Konfigurasi Tambahan

### Gunakan environment variable (lebih aman untuk production):

```bash
# Linux/Mac
export TELEGRAM_BOT_TOKEN="token_kamu"
export TELEGRAM_CHAT_ID="chat_id_kamu"
python monitor.py

# Windows
set TELEGRAM_BOT_TOKEN=token_kamu
set TELEGRAM_CHAT_ID=chat_id_kamu
python monitor.py
```

### Ubah threshold dan interval:

```python
# config.py
ALERT_THRESHOLD_HOURS  = 3    # Kirim alert jika > 3 jam
CHECK_INTERVAL_MINUTES = 30   # Cek setiap 30 menit
```

---

## 📊 Contoh Output Log

```
[2024-01-15 08:00:00] INFO     ═══════════════════════════════════════════
[2024-01-15 08:00:00] INFO     Monitoring dimulai — 2024-01-15 08:00:00
[2024-01-15 08:00:00] INFO     ═══════════════════════════════════════════
[2024-01-15 08:00:00] INFO     Memeriksa Lobby Depan → /nas/cctv/cam1
[2024-01-15 08:00:00] INFO     [Lobby Depan] File terakhir: 07:45:12 | Delay: 14 menit
[2024-01-15 08:00:00] INFO     [Lobby Depan] OK ✓
[2024-01-15 08:00:00] INFO     Memeriksa Parkiran → /nas/cctv/cam2
[2024-01-15 08:00:00] WARNING  [Parkiran] DOWN! Delay: 4 jam 5 menit. Mengirim notifikasi...
[2024-01-15 08:00:01] INFO     Notifikasi Telegram berhasil dikirim.
```

---

## 💡 Tips & Troubleshooting

| Masalah                   | Solusi                                   |
| ------------------------- | ---------------------------------------- |
| "Folder tidak ditemukan"  | Pastikan NAS ter-mount dan path benar    |
| "Timeout Telegram"        | Cek koneksi internet server              |
| Notifikasi berulang-ulang | Cek file `state/camera_states.json`      |
| Script berhenti sendiri   | Gunakan systemd atau supervisor          |
| Bot tidak merespons       | Pastikan sudah pernah kirim pesan ke bot |

---

## 🚀 Pengembangan Lanjutan (Opsional)

### 1. Dashboard Web (Flask/Streamlit)

Tambahkan web dashboard untuk melihat status semua kamera secara real-time.
Baca state dari `state/camera_states.json` dan tampilkan di browser.

**Teknologi:** Flask + Jinja2 (sederhana) atau Streamlit (cepat dibuat)

### 2. Database (SQLite/PostgreSQL)

Simpan history alert ke database untuk audit trail dan analisis.
Berguna untuk melihat pola: kamera mana yang paling sering bermasalah.

**Tabel minimal:**

- `camera_events`: cam_name, event_type (DOWN/UP/ERROR), timestamp, delay_hours

### 3. Scaling untuk CCTV Banyak (50+)

- Gunakan `concurrent.futures.ThreadPoolExecutor` untuk cek kamera secara paralel
- Pisahkan konfigurasi ke database, bukan hardcode di config.py
- Tambahkan retry mechanism untuk pengiriman Telegram
- Gunakan queue (Redis) untuk buffer notifikasi

### 4. Multi-Channel Notifikasi

Tambahkan notifikasi ke WhatsApp (via Twilio), Email (SMTP), atau Slack.
Cukup tambahkan fungsi `send_whatsapp()` / `send_email()` di samping `send_telegram()`.
