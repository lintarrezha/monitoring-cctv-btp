"""
config.py — Konfigurasi utama CCTV Monitoring System
=====================================================
Semua pengaturan ada di sini. Token Telegram dibaca
dari file .env agar tidak hardcode di source code.
"""

import os
from dotenv import load_dotenv

# Baca file .env secara otomatis
load_dotenv()


class Config:

    # ─────────────────────────────────────────────────────
    # PATH UTAMA
    # Folder induk yang berisi semua subfolder kamera.
    # Sistem akan auto-scan semua subfolder di dalamnya.
    # ─────────────────────────────────────────────────────
    BASE_PATH = r"C:\Users\USER\PROJECT CODING\test"

    # ─────────────────────────────────────────────────────
    # ATURAN MONITORING
    # ─────────────────────────────────────────────────────

    # Kirim alert jika tidak ada file baru lebih dari X detik.
    # CCTV kirim tiap 30 menit → threshold 1 jam = wajar.
    # Untuk testing → ubah ke 180 (3 menit)
    # NO_FILE_LIMIT_SECONDS = 60 * 60      # 1 jam (production)
    NO_FILE_LIMIT_SECONDS = 60 * 3    # 3 menit (testing)

    # Seberapa sering polling fallback berjalan (detik).
    # Polling berfungsi sebagai cadangan jika Watchdog
    # tidak menangkap event dari network drive (NAS).
    POLLING_INTERVAL_SECONDS = 5 * 60   # setiap 5 menit

    # Ekstensi file yang dianggap sebagai gambar CCTV
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    # Format tanggal pada nama folder harian CCTV
    # Contoh: 2026_04_30-2026_04_30 → ambil bagian pertama: 2026_04_30
    DAILY_FOLDER_DATE_FORMAT = "%Y_%m_%d"

    # ─────────────────────────────────────────────────────
    # TELEGRAM
    # Nilai dibaca dari file .env — JANGAN hardcode di sini!
    # ─────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

    # ─────────────────────────────────────────────────────
    # FILE OUTPUT
    # ─────────────────────────────────────────────────────
    BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
    LOG_FILE   = os.path.join(BASE_DIR, "logs", "monitoring.log")
    STATE_FILE = os.path.join(BASE_DIR, "state", "camera_states.json")