"""
test_setup.py — Validasi setup sebelum menjalankan monitor.py
=============================================================
Jalankan ini PERTAMA KALI sebelum monitor.py.

Yang ditest:
  1. Semua library Python terinstall
  2. File .env ada dan token sudah diisi
  3. Koneksi Telegram berhasil (pesan tes dikirim ke HP)
  4. Simulasi struktur folder CCTV → logika pembacaan dicek

Cara pakai:
    python test_setup.py
"""

import sys
import os
import re
import shutil
import requests

from pathlib import Path
from datetime import datetime, timedelta


def test_imports():
    print("\n[1/4] Mengecek library Python...")
    libs    = ["requests", "watchdog", "dotenv", "schedule"]
    all_ok  = True

    for lib in libs:
        try:
            __import__(lib)
            print(f"  ✓ {lib}")
        except ImportError:
            # dotenv diimport sebagai python_dotenv
            if lib == "dotenv":
                try:
                    import dotenv
                    print(f"  ✓ python-dotenv")
                    continue
                except ImportError:
                    pass
            print(f"  ✗ {lib} — belum terinstall")
            print(f"    Jalankan: pip install {lib}")
            all_ok = False

    return all_ok


def test_env_file():
    print("\n[2/4] Mengecek file .env...")

    env_path = Path(".env")

    if not env_path.exists():
        print("  ✗ File .env tidak ditemukan!")
        print("    Salin .env.example menjadi .env lalu isi token dan chat_id.")
        return False

    print("  ✓ File .env ditemukan.")

    # Baca isi .env
    content = env_path.read_text(encoding="utf-8")
    token_ok   = "TELEGRAM_BOT_TOKEN=" in content and "MASUKKAN" not in content
    chat_ok    = "TELEGRAM_CHAT_ID=" in content and "MASUKKAN" not in content

    if not token_ok:
        print("  ✗ TELEGRAM_BOT_TOKEN belum diisi di .env!")
        return False

    if not chat_ok:
        print("  ✗ TELEGRAM_CHAT_ID belum diisi di .env!")
        return False

    print("  ✓ TELEGRAM_BOT_TOKEN terisi.")
    print("  ✓ TELEGRAM_CHAT_ID terisi.")
    return True


def test_telegram():
    print("\n[3/4] Mengecek koneksi Telegram...")

    try:
        from config import Config
    except ImportError:
        print("  ✗ config.py tidak ditemukan!")
        return False

    token   = Config.TELEGRAM_BOT_TOKEN
    chat_id = Config.TELEGRAM_CHAT_ID

    if not token or "MASUKKAN" in token:
        print("  ✗ Token Telegram belum diisi. Isi dulu di .env")
        return False

    print(f"  Token   : {token[:10]}...{token[-5:]}")
    print(f"  Chat ID : {chat_id}")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    msg = (
        f"✅ <b>Test Koneksi Berhasil!</b>\n\n"
        f"CCTV Monitoring System siap dijalankan.\n"
        f"Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"📋 Konfigurasi:\n"
        f"  Threshold  : {Config.NO_FILE_LIMIT_SECONDS // 60} menit\n"
        f"  Polling    : setiap {Config.POLLING_INTERVAL_SECONDS // 60} menit\n"
        f"  Base path  : <code>{Config.BASE_PATH}</code>"
    )

    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
        r.raise_for_status()
        print("  ✓ Pesan tes berhasil dikirim ke Telegram!")
        return True
    except requests.exceptions.HTTPError as e:
        print(f"  ✗ HTTP Error: {e}")
        print("    Pastikan token dan chat_id benar.")
    except requests.exceptions.ConnectionError:
        print("  ✗ Tidak bisa terhubung ke internet / Telegram API.")

    return False


def test_folder_logic():
    """
    Buat folder simulasi persis seperti struktur CCTV asli,
    lalu tes apakah sistem bisa membacanya dengan benar.

    Skenario:
      cam1 → file 20 menit lalu  → harusnya OK
      cam2 → file 90 menit lalu  → harusnya TIMEOUT (> 60 menit)
      cam3 → folder tanggal kosong → harusnya ERROR
      cam4 → ada dua folder tanggal → harusnya ambil yang terbaru
    """
    print("\n[4/4] Simulasi struktur folder CCTV...")

    sim     = Path("cctv_sim_test")
    today   = datetime.now().strftime("%Y_%m_%d")
    yest    = (datetime.now() - timedelta(days=1)).strftime("%Y_%m_%d")
    tf      = f"{today}-{today}"    # today folder
    yf      = f"{yest}-{yest}"      # yesterday folder

    # Buat folder simulasi
    (sim / "cctv seminyak 1" / tf).mkdir(parents=True)
    (sim / "cctv seminyak 2" / tf).mkdir(parents=True)
    (sim / "cctv seminyak 3" / tf).mkdir(parents=True)
    (sim / "cctv seminyak 4" / yf).mkdir(parents=True)
    (sim / "cctv seminyak 4" / tf).mkdir(parents=True)

    def make_file(path: Path, minutes_ago: int):
        path.write_text("dummy")
        t = (datetime.now() - timedelta(minutes=minutes_ago)).timestamp()
        os.utime(path, (t, t))

    # cam1: file 20 menit lalu → OK
    make_file(sim / "cctv seminyak 1" / tf / "snap_001.jpg", 20)

    # cam2: file 90 menit lalu → TIMEOUT
    make_file(sim / "cctv seminyak 2" / tf / "snap_old.jpg", 90)

    # cam3: folder kosong → ERROR
    # (tidak ada file)

    # cam4: dua folder tanggal → harus baca yang terbaru (tf)
    make_file(sim / "cctv seminyak 4" / yf / "snap_old.jpg", 500)
    make_file(sim / "cctv seminyak 4" / tf / "snap_new.jpg", 25)

    # Import fungsi dari monitor
    sys.path.insert(0, str(Path(__file__).parent))
    from monitor import (
        scan_all_cameras,
        get_latest_date_folder,
        get_latest_jpg,
        format_elapsed,
    )
    import time

    cameras     = scan_all_cameras(str(sim))
    threshold   = 60 * 60   # 1 jam dalam detik
    all_ok      = True

    print(f"\n  Kamera ditemukan: {[Path(k).name for k, _ in cameras]}\n")

    for cam_key, cam_path in cameras:
        cam_name      = cam_path.name
        date_folder   = get_latest_date_folder(cam_path)

        if date_folder is None:
            print(f"  [{cam_name}]")
            print(f"    Folder tanggal : TIDAK DITEMUKAN ✗")
            all_ok = False
            continue

        latest_jpg = get_latest_jpg(date_folder)

        print(f"  [{cam_name}]")
        print(f"    Folder terbaru : {date_folder.name}")

        if latest_jpg is None:
            print(f"    File jpg       : TIDAK ADA (folder kosong) ✗")
            continue

        elapsed    = time.time() - latest_jpg.stat().st_mtime
        status     = "TIMEOUT ⚠️" if elapsed >= threshold else "OK ✓"
        print(f"    File terbaru   : {latest_jpg.name}")
        print(f"    Delay          : {format_elapsed(elapsed)} → {status}")

    # Hapus simulasi
    shutil.rmtree(sim)
    print(f"\n  Folder simulasi dihapus otomatis.")

    return all_ok


if __name__ == "__main__":
    print("=" * 58)
    print("  CCTV Monitoring System — Setup Validation")
    print("=" * 58)

    r1 = test_imports()
    r2 = test_env_file()
    r3 = test_telegram() if r2 else False
    r4 = test_folder_logic() if r1 else False

    print("\n" + "=" * 58)
    if r1 and r2 and r3 and r4:
        print("  🎉 Semua tes berhasil!")
        print("     Jalankan: python monitor.py")
    else:
        print("  ⚠️  Ada tes yang gagal. Perbaiki dulu sebelum lanjut.")
    print("=" * 58)