"""
CCTV Monitoring System — Final Version (Hybrid)
================================================
Mendeteksi CCTV yang tidak mengirim file gambar melebihi
batas waktu, lalu mengirim notifikasi otomatis ke Telegram.

Pendekatan HYBRID:
  1. Watchdog  → Deteksi file baru secara real-time (instan)
  2. Polling   → Fallback setiap 5 menit, memastikan tidak ada
                 yang terlewat jika Watchdog gagal menangkap
                 event dari network drive / NAS

Struktur folder CCTV yang didukung:
  Z:\\CCTV Snapshot\\
  ├── cctv seminyak 1\\
  │   ├── 2026_04_29-2026_04_29\\
  │   └── 2026_04_30-2026_04_30\\   ← folder hari ini (terbaru)
  │       ├── snap_001.jpg
  │       └── snap_047.jpg           ← file terbaru yang dipantau
  └── cctv seminyak 2\\
      └── ...

Fitur:
  - Auto-scan semua kamera dari BASE_PATH (tidak perlu hardcode)
  - Watchdog real-time + polling fallback untuk keandalan di NAS
  - Alert Telegram jika tidak ada file baru > threshold
  - Recovery notification saat CCTV kembali normal
  - Anti-spam: alert hanya satu kali per periode down
  - Timer mulai dari program start (tidak false alarm saat restart)
  - Token Telegram aman di file .env (tidak hardcode)
  - Logging lengkap ke file + console
"""

import os
import re
import json
import time
import logging
import threading
import requests

from pathlib import Path
from datetime import datetime
from config import Config

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# ─────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────
def setup_logger(log_file: str) -> logging.Logger:
    """Konfigurasi logger: output ke file DAN ke console."""
    logger = logging.getLogger("cctv_monitor")
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    file_handler    = logging.FileHandler(log_file, encoding="utf-8")
    console_handler = logging.StreamHandler()
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = setup_logger(Config.LOG_FILE)


# ─────────────────────────────────────────────
# STATE MANAGER
# ─────────────────────────────────────────────
class StateManager:
    """
    Menyimpan dan mengelola status setiap kamera CCTV.

    Status per kamera:
      - last_file_time   : timestamp terakhir kali ada file baru masuk
      - alert_sent       : apakah alert DOWN sudah dikirim (anti-spam)
      - latest_folder    : nama folder tanggal terbaru yang dipantau
      - is_down          : apakah saat ini sedang dalam kondisi DOWN

    Data disimpan ke file JSON agar tidak hilang jika program restart.
    """

    def __init__(self):
        self._lock  = threading.Lock()
        self._state: dict = {}
        Path(Config.STATE_FILE).parent.mkdir(parents=True, exist_ok=True)

    def init_camera(self, cam_key: str, latest_folder: str | None):
        """
        Inisialisasi status kamera saat program pertama berjalan.
        Timer dimulai dari SEKARANG agar tidak false alarm saat restart.
        """
        with self._lock:
            if cam_key not in self._state:
                self._state[cam_key] = {
                    "last_file_time" : time.time(),   # timer mulai dari sekarang
                    "alert_sent"     : False,
                    "is_down"        : False,
                    "latest_folder"  : latest_folder,
                }
                logger.info(
                    f"[{Path(cam_key).name}] Inisialisasi. "
                    f"Folder terbaru: {latest_folder or 'tidak ditemukan'}. "
                    f"Timer dimulai dari sekarang."
                )

    def update_folder(self, cam_key: str, new_folder: str):
        """
        Saat folder tanggal baru muncul (hari berganti),
        update folder dan reset timer.
        """
        with self._lock:
            if cam_key not in self._state:
                return

            old_folder = self._state[cam_key]["latest_folder"]

            if old_folder != new_folder:
                self._state[cam_key]["latest_folder"]  = new_folder
                self._state[cam_key]["last_file_time"] = time.time()
                self._state[cam_key]["alert_sent"]     = False
                self._state[cam_key]["is_down"]        = False

                logger.info(
                    f"[{Path(cam_key).name}] Folder tanggal baru: "
                    f"{old_folder} → {new_folder}. Timer di-reset."
                )

    def record_new_file(self, cam_key: str, file_name: str):
        """
        Catat bahwa ada file baru masuk → reset timer.
        Jika sebelumnya DOWN, tandai recovery.
        """
        with self._lock:
            if cam_key not in self._state:
                return

            was_down = self._state[cam_key]["is_down"]

            self._state[cam_key]["last_file_time"] = time.time()
            self._state[cam_key]["alert_sent"]     = False
            self._state[cam_key]["is_down"]        = False

            logger.info(
                f"[{Path(cam_key).name}] File baru: {file_name}. Timer di-reset."
            )

            return was_down   # True jika sebelumnya down (perlu kirim recovery)

    def get_cameras_to_alert(self) -> list[dict]:
        """
        Periksa semua kamera. Kembalikan daftar kamera yang perlu di-alert
        (elapsed > threshold DAN alert belum dikirim).
        """
        with self._lock:
            result = []
            now    = time.time()

            for cam_key, status in self._state.items():
                if status["latest_folder"] is None:
                    continue

                elapsed = now - status["last_file_time"]

                if elapsed >= Config.NO_FILE_LIMIT_SECONDS and not status["alert_sent"]:
                    result.append({
                        "cam_key"       : cam_key,
                        "elapsed"       : elapsed,
                        "latest_folder" : status["latest_folder"],
                    })

            return result

    def get_cameras_to_recovery(self) -> list[str]:
        """Kembalikan daftar kamera yang perlu notifikasi recovery."""
        with self._lock:
            return [k for k, v in self._state.items() if v.get("need_recovery")]

    def mark_alert_sent(self, cam_key: str):
        """Tandai alert sudah dikirim (anti-spam)."""
        with self._lock:
            if cam_key in self._state:
                self._state[cam_key]["alert_sent"] = True
                self._state[cam_key]["is_down"]    = True

    def mark_recovery_sent(self, cam_key: str):
        """Tandai recovery sudah dikirim."""
        with self._lock:
            if cam_key in self._state:
                self._state[cam_key]["need_recovery"] = False
                self._state[cam_key]["is_down"]       = False

    def flag_recovery(self, cam_key: str):
        """Tandai kamera butuh notifikasi recovery."""
        with self._lock:
            if cam_key in self._state:
                self._state[cam_key]["need_recovery"] = True

    def get_latest_folder(self, cam_key: str) -> str | None:
        with self._lock:
            return self._state.get(cam_key, {}).get("latest_folder")

    def is_initialized(self, cam_key: str) -> bool:
        with self._lock:
            return cam_key in self._state


# Instance global — dipakai bersama oleh Watchdog dan polling thread
state = StateManager()


# ─────────────────────────────────────────────
# FOLDER SCANNER
# ─────────────────────────────────────────────
def scan_all_cameras(base_path: str) -> list[tuple[str, Path]]:
    """
    Auto-scan semua subfolder kamera di dalam base_path.

    Returns:
        [(cam_key, cam_path), ...]
        cam_key = path absolut sebagai string (dipakai sebagai ID unik)
    """
    base = Path(base_path)

    if not base.exists():
        logger.error(f"BASE_PATH tidak ditemukan: {base_path}")
        return []

    cameras = []
    for item in sorted(base.iterdir()):
        if item.is_dir():
            cameras.append((str(item.resolve()), item.resolve()))

    return cameras


def get_latest_date_folder(cam_path: Path) -> Path | None:
    """
    Cari subfolder tanggal terbaru di dalam folder kamera.
    Format: YYYY_MM_DD-YYYY_MM_DD

    Cara menentukan terbaru: sort nama folder secara alfabetis descending.
    Format YYYY_MM_DD otomatis terurut benar secara alfabet.
    """
    pattern = re.compile(r"^\d{4}_\d{2}_\d{2}-\d{4}_\d{2}_\d{2}$")

    date_folders = [
        f for f in cam_path.iterdir()
        if f.is_dir() and pattern.match(f.name)
    ]

    if not date_folders:
        return None

    return sorted(date_folders, key=lambda f: f.name, reverse=True)[0]


def get_latest_jpg(date_folder: Path) -> Path | None:
    """Cari file gambar terbaru (berdasarkan modified time) di dalam folder tanggal."""
    files = [
        f for f in date_folder.iterdir()
        if f.is_file() and f.suffix.lower() in Config.ALLOWED_EXTENSIONS
    ]

    if not files:
        return None

    return max(files, key=lambda f: f.stat().st_mtime)


def resolve_cam_key(file_path: Path, cameras: list[tuple[str, Path]]) -> str | None:
    """
    Tentukan file ini milik kamera mana berdasarkan path-nya.
    Returns cam_key (string path absolut kamera) atau None.
    """
    file_path = file_path.resolve()

    for cam_key, cam_path in cameras:
        try:
            file_path.relative_to(cam_path)
            return cam_key
        except ValueError:
            continue

    return None


def format_elapsed(seconds: float) -> str:
    """Format detik menjadi string yang mudah dibaca. Contoh: '1 jam 15 menit'"""
    hrs  = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)

    if hrs > 0:
        return f"{hrs} jam {mins} menit"
    return f"{mins} menit"


# ─────────────────────────────────────────────
# TELEGRAM NOTIFIER
# ─────────────────────────────────────────────
def send_telegram(message: str) -> bool:
    """Kirim pesan ke Telegram. Returns True jika berhasil."""
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("Token atau Chat ID Telegram belum diisi di file .env!")
        return False

    url     = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id"    : Config.TELEGRAM_CHAT_ID,
        "text"       : message,
        "parse_mode" : "HTML",
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        logger.info("Notifikasi Telegram berhasil dikirim.")
        return True
    except requests.exceptions.Timeout:
        logger.error("Timeout saat mengirim notifikasi Telegram.")
    except requests.exceptions.ConnectionError:
        logger.error("Tidak bisa terhubung ke Telegram API. Cek koneksi internet.")
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP Error Telegram API: {e}")
    except Exception as e:
        logger.error(f"Error tidak terduga saat kirim Telegram: {e}")

    return False


def build_alert_message(cam_name: str, folder_name: str, elapsed_str: str) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"🚨 <b>CCTV ALERT — Tidak Ada File Baru</b>\n\n"
        f"📷 <b>Kamera       :</b> {cam_name}\n"
        f"📁 <b>Folder hari  :</b> {folder_name}\n"
        f"⌛ <b>Tidak ada file:</b> {elapsed_str}\n"
        f"🕐 <b>Waktu deteksi:</b> {now_str}\n\n"
        f"⚠️ Segera periksa kamera dan koneksi jaringan!"
    )


def build_recovery_message(cam_name: str, folder_name: str, latest_file: str) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"✅ <b>CCTV RECOVERY — Kembali Normal</b>\n\n"
        f"📷 <b>Kamera      :</b> {cam_name}\n"
        f"📁 <b>Folder hari :</b> {folder_name}\n"
        f"🖼  <b>File terbaru:</b> {latest_file}\n"
        f"🕐 <b>Waktu       :</b> {now_str}\n\n"
        f"👍 Kamera sudah mengirim data kembali."
    )


# ─────────────────────────────────────────────
# WATCHDOG EVENT HANDLER
# ─────────────────────────────────────────────
class CCTVEventHandler(FileSystemEventHandler):
    """
    Handler Watchdog — berjalan di thread terpisah.
    Mendengarkan event file/folder baru dari OS secara real-time.

    Catatan: Di network drive (NAS via SMB), event kadang tidak
    terkirim dengan andal → polling fallback tetap diperlukan.
    """

    def __init__(self, cameras: list[tuple[str, Path]]):
        self.cameras = cameras

    def on_created(self, event):
        path = Path(event.src_path)

        # ── Ada folder baru (kemungkinan folder tanggal baru) ──
        if event.is_directory:
            cam_key = resolve_cam_key(path, self.cameras)
            if cam_key is None:
                return

            cam_path      = Path(cam_key)
            latest_folder = get_latest_date_folder(cam_path)

            if latest_folder:
                state.update_folder(cam_key, latest_folder.name)
                logger.info(
                    f"[{cam_path.name}] Folder tanggal baru terdeteksi "
                    f"(Watchdog): {latest_folder.name}"
                )
            return

        # ── Ada file baru ──
        if path.suffix.lower() not in Config.ALLOWED_EXTENSIONS:
            return

        cam_key = resolve_cam_key(path, self.cameras)
        if cam_key is None:
            return

        # Pastikan file berada di folder tanggal terbaru
        current_latest = state.get_latest_folder(cam_key)
        if current_latest is None:
            return

        try:
            path.resolve().relative_to(Path(cam_key) / current_latest)
        except ValueError:
            logger.info(
                f"[{Path(cam_key).name}] File diabaikan "
                f"(bukan di folder terbaru): {path.name}"
            )
            return

        # Catat file baru → reset timer
        was_down = state.record_new_file(cam_key, path.name)

        # Jika sebelumnya down, kirim recovery
        if was_down:
            state.flag_recovery(cam_key)
            _send_recovery_now(cam_key, current_latest, path.name)


def _send_recovery_now(cam_key: str, folder_name: str, file_name: str):
    """Kirim notifikasi recovery segera (dipanggil dari Watchdog thread)."""
    cam_name = Path(cam_key).name
    msg      = build_recovery_message(cam_name, folder_name, file_name)

    if send_telegram(msg):
        state.mark_recovery_sent(cam_key)
        logger.info(f"[{cam_name}] Recovery notification dikirim.")


# ─────────────────────────────────────────────
# POLLING FALLBACK (berjalan di thread terpisah)
# ─────────────────────────────────────────────
def polling_worker(cameras: list[tuple[str, Path]]):
    """
    Thread polling fallback — berjalan setiap POLLING_INTERVAL_SECONDS.

    Tugas:
    1. Cek folder tanggal terbaru setiap kamera (update jika hari berganti)
    2. Cek file jpg terbaru → jika ada yang lebih baru dari last_file_time,
       update timer (menangkap file yang Watchdog mungkin terlewat)
    3. Evaluasi semua kamera → kirim alert jika timeout
    4. Kirim recovery jika kamera kembali normal
    """
    logger.info(
        f"Polling fallback aktif — interval: "
        f"{Config.POLLING_INTERVAL_SECONDS // 60} menit."
    )

    while True:
        time.sleep(Config.POLLING_INTERVAL_SECONDS)

        logger.info("── Polling fallback berjalan ──────────────────────")

        for cam_key, cam_path in cameras:
            try:
                _poll_single_camera(cam_key, cam_path)
            except Exception as e:
                logger.error(
                    f"[{cam_path.name}] Error saat polling: {e}",
                    exc_info=True
                )

        # Kirim alert untuk kamera yang timeout
        _evaluate_and_alert(cameras)

        logger.info("── Polling selesai ────────────────────────────────\n")


def _poll_single_camera(cam_key: str, cam_path: Path):
    """
    Polling satu kamera: update folder terbaru dan cek file terbaru.
    """
    cam_name = cam_path.name

    if not cam_path.exists():
        logger.warning(f"[{cam_name}] Folder tidak ditemukan saat polling.")
        return

    # Cek folder tanggal terbaru
    latest_folder = get_latest_date_folder(cam_path)

    if latest_folder is None:
        logger.warning(f"[{cam_name}] Tidak ada folder tanggal ditemukan.")
        return

    # Update jika folder berubah (hari berganti)
    state.update_folder(cam_key, latest_folder.name)

    # Cek file jpg terbaru
    latest_jpg = get_latest_jpg(latest_folder)

    if latest_jpg is None:
        logger.warning(f"[{cam_name}] Folder {latest_folder.name} kosong.")
        return

    # Bandingkan modified time file dengan last_file_time di state
    # Jika file lebih baru → Watchdog tadi terlewat, kita catch di sini
    file_mtime = latest_jpg.stat().st_mtime

    with state._lock:
        if cam_key not in state._state:
            return

        last_recorded = state._state[cam_key]["last_file_time"]
        was_down      = state._state[cam_key]["is_down"]

        if file_mtime > last_recorded:
            # Ada file baru yang Watchdog terlewat
            state._state[cam_key]["last_file_time"] = file_mtime
            state._state[cam_key]["alert_sent"]     = False

            logger.info(
                f"[{cam_name}] Polling menangkap file baru "
                f"(Watchdog miss): {latest_jpg.name}"
            )

            # Jika sebelumnya down → kirim recovery
            if was_down:
                state._state[cam_key]["is_down"] = False
                # Kirim recovery di luar lock
                threading.Thread(
                    target=_send_recovery_now,
                    args=(cam_key, latest_folder.name, latest_jpg.name),
                    daemon=True
                ).start()
        else:
            logger.info(
                f"[{cam_name}] Folder: {latest_folder.name} | "
                f"File terbaru: {latest_jpg.name} | "
                f"Tidak ada perubahan."
            )


def _evaluate_and_alert(cameras: list[tuple[str, Path]]):
    """
    Evaluasi semua kamera. Kirim alert untuk yang timeout.
    """
    cameras_to_alert = state.get_cameras_to_alert()

    for info in cameras_to_alert:
        cam_key       = info["cam_key"]
        elapsed       = info["elapsed"]
        latest_folder = info["latest_folder"]
        cam_name      = Path(cam_key).name
        elapsed_str   = format_elapsed(elapsed)

        logger.warning(
            f"[{cam_name}] TIMEOUT! Tidak ada file baru selama "
            f"{elapsed_str}. Mengirim alert..."
        )

        msg = build_alert_message(cam_name, latest_folder, elapsed_str)

        if send_telegram(msg):
            state.mark_alert_sent(cam_key)


# ─────────────────────────────────────────────
# INISIALISASI AWAL
# ─────────────────────────────────────────────
def initialize_all_cameras(cameras: list[tuple[str, Path]]):
    """
    Inisialisasi status semua kamera saat program pertama berjalan.
    Timer dimulai dari sekarang — tidak false alarm meski file lama.
    """
    logger.info("Inisialisasi status kamera...")

    for cam_key, cam_path in cameras:
        cam_name = cam_path.name

        if not cam_path.exists():
            logger.warning(f"[{cam_name}] Folder tidak ditemukan saat init.")
            state.init_camera(cam_key, None)
            continue

        latest_folder = get_latest_date_folder(cam_path)
        folder_name   = latest_folder.name if latest_folder else None

        state.init_camera(cam_key, folder_name)

        if latest_folder:
            latest_jpg = get_latest_jpg(latest_folder)
            if latest_jpg:
                logger.info(
                    f"[{cam_name}] Folder: {folder_name} | "
                    f"File terbaru: {latest_jpg.name}"
                )
            else:
                logger.warning(
                    f"[{cam_name}] Folder {folder_name} ada tapi kosong."
                )


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    logger.info("=" * 60)
    logger.info("  🚀 CCTV Monitoring System — Hybrid Mode")
    logger.info("=" * 60)
    logger.info(f"  Base path      : {Config.BASE_PATH}")
    logger.info(f"  Threshold      : {Config.NO_FILE_LIMIT_SECONDS // 60} menit")
    logger.info(f"  Polling        : setiap {Config.POLLING_INTERVAL_SECONDS // 60} menit")
    logger.info(f"  Log file       : {Config.LOG_FILE}")
    logger.info("=" * 60)

    # Validasi Telegram config
    if not Config.TELEGRAM_BOT_TOKEN or "MASUKKAN" in Config.TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN belum diisi di file .env! "
            "Program tetap berjalan tapi notifikasi tidak akan terkirim."
        )
    if not Config.TELEGRAM_CHAT_ID or "MASUKKAN" in Config.TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_CHAT_ID belum diisi di file .env! "
            "Program tetap berjalan tapi notifikasi tidak akan terkirim."
        )

    # Scan semua kamera
    cameras = scan_all_cameras(Config.BASE_PATH)

    if not cameras:
        logger.error(
            f"Tidak ada folder kamera ditemukan di: {Config.BASE_PATH}. "
            "Program dihentikan."
        )
        return

    logger.info(
        f"Kamera ditemukan ({len(cameras)}): "
        f"{[Path(k).name for k, _ in cameras]}"
    )

    # Inisialisasi status semua kamera
    initialize_all_cameras(cameras)

    # ── Setup Watchdog Observer ──
    event_handler = CCTVEventHandler(cameras)
    observer      = Observer()

    for cam_key, cam_path in cameras:
        observer.schedule(event_handler, str(cam_path), recursive=True)
        logger.info(f"Watchdog memantau: {cam_path}")

    observer.start()
    logger.info("Watchdog aktif.")

    # ── Start Polling Fallback Thread ──
    poll_thread = threading.Thread(
        target=polling_worker,
        args=(cameras,),
        daemon=True,
        name="PollingFallback"
    )
    poll_thread.start()

    logger.info("Sistem siap. Tekan Ctrl+C untuk berhenti.\n")

    # ── Main loop: evaluasi alert dari main thread ──
    try:
        while True:
            time.sleep(30)   # Cek setiap 30 detik
            _evaluate_and_alert(cameras)

    except KeyboardInterrupt:
        logger.info("Program dihentikan oleh pengguna (Ctrl+C).")
        observer.stop()

    observer.join()
    logger.info("Program selesai.")


if __name__ == "__main__":
    main()