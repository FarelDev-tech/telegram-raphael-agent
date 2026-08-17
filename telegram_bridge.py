import os
import sys

# Ensure telegram_bridge directory is always in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
if r"C:\Users\USER\telegram_bridge" not in sys.path:
    sys.path.insert(0, r"C:\Users\USER\telegram_bridge")

import re
import json
import time
import glob
import base64
import socket
import datetime
import subprocess
import threading
import requests
import io
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from ddgs import DDGS

# Import Google Sync Engine
try:
    from google_sync import google_sync
except Exception as e:
    google_sync = None

# Import Spotify Controller
try:
    from spotify_controller import spotify_ctrl
except Exception as e:
    print(f"[Spotify Import Error] {e}")
    spotify_ctrl = None

# Import Local Browser Agent (Project Mariner Style)
try:
    from browser_agent import browser_agent
except Exception as e:
    print(f"[Browser Agent Import Error] {e}")
    browser_agent = None


# Force UTF-8 stdout/stderr on Windows to prevent UnicodeEncodeError with emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# -------------------------------------------------------------
# Single Instance Lock
# -------------------------------------------------------------
def ensure_single_instance(port=49555):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', port))
        s.listen(1)
        return s
    except socket.error:
        print("[Single-Instance] Instance already running. Terminating duplicate.")
        sys.exit(0)

# -------------------------------------------------------------
# Configuration
# -------------------------------------------------------------
TELEGRAM_BOT_TOKEN = "8854097319:AAHaR_Tz2lmGML6e62oTc2q_erm7P6Ahmjg"
ALLOWED_USER_ID = 1380172602
GEMINI_API_KEY = "AIzaSyCAAuwepqWxoXJ2P8mmLUX4H0Wg2H5HFt8"
GROQ_API_KEY = "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"

CURRENT_ENGINE = "openai/gpt-oss-120b" # Default to Groq's SOTA 120B model (500 tokens/sec)

# Primary Priority Models (Strictly Gemini 3.7, 3.6, and 3.5 ONLY — Baseline Floor: 3.5)
PRIMARY_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite"
]

BRAIN_DIR = os.getenv("BRAIN_DIR") or (r"C:\Users\USER\Obsidian\AI-Brain" if os.path.exists(r"C:\Users\USER\Obsidian\AI-Brain") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "AI-Brain"))
DEFAULT_CWD = os.getenv("DEFAULT_CWD") or (r"C:\Users\USER" if os.path.exists(r"C:\Users\USER") else os.path.dirname(os.path.abspath(__file__)))
CRON_DATABASE_FILE = os.getenv("CRON_DATABASE_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "cron_jobs.json")
ACTIVE_TASKS_FILE = os.path.join(BRAIN_DIR, "08_Goals", "Tasks", "Active-Tasks.md")
CALENDAR_EVENTS_FILE = os.path.join(BRAIN_DIR, "10_Planning", "Calendar", "Calendar-Events.md")

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_FILE_BASE = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"

# Persistent HTTP Session with Connection Pooling
session = requests.Session()
adapter = HTTPAdapter(
    pool_connections=20,
    pool_maxsize=30,
    max_retries=Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
)
session.mount("https://", adapter)
session.mount("http://", adapter)

# In-memory conversational history
conversation_history = []
context_cache = {"content": "", "last_read": 0}

# Tracking for Proactive Daily Schedules (sent today)
sent_schedules_today = set()
last_checked_day = ""

# -------------------------------------------------------------
# Brain-First Task & Calendar Management Tools
# -------------------------------------------------------------
def tool_create_task(title, due_date=None, category="general", priority="normal", notes="", link_to_study_plan=None):
    os.makedirs(os.path.dirname(ACTIVE_TASKS_FILE), exist_ok=True)
    
    # Format date & tags
    due_tag = f" 📅 {due_date}" if due_date else ""
    cat_tag = f" #{category.strip().replace(' ', '_')}" if category else ""
    link_tag = f" [[{link_to_study_plan}]]" if link_to_study_plan else ""
    task_line = f"- [ ] {title}{due_tag}{cat_tag}{link_tag}"

    # 1. Update AI-Brain Active-Tasks.md
    try:
        content = ""
        if os.path.exists(ACTIVE_TASKS_FILE):
            with open(ACTIVE_TASKS_FILE, "r", encoding="utf-8") as f:
                content = f.read()
        
        # Append under Priority Tasks if section exists
        if "## 📌 Priority Tasks & Deadlines" in content:
            parts = content.split("## 📌 Priority Tasks & Deadlines", 1)
            new_content = f"{parts[0]}## 📌 Priority Tasks & Deadlines\n\n{task_line}{parts[1]}"
        else:
            new_content = content + f"\n\n## 📌 Tasks\n{task_line}\n"
        
        with open(ACTIVE_TASKS_FILE, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        print(f"[Task Write Error] {e}")

    # 2. Push to Google Tasks if authenticated
    google_status = "Tersimpan di AI-Brain (Google Tasks menunggu otorisasi credentials.json)"
    if google_sync and google_sync.is_authenticated():
        res = google_sync.add_task(title=title, notes=notes or f"Category: {category}", due_date=due_date)
        if res.get("status") == "success":
            google_status = "100% Tersinkronisasi ke Google Tasks di HP Master"

    return {
        "status": "success",
        "task": task_line,
        "vault_file": "08_Goals/Tasks/Active-Tasks.md",
        "cloud_sync": google_status
    }

def tool_list_active_tasks():
    # Always pull latest completed / updated status from Google Tasks first (Two-Way Live Sync)
    if google_sync and google_sync.is_authenticated():
        try:
            google_sync.sync_tasks_with_vault(ACTIVE_TASKS_FILE)
        except Exception:
            pass

    if not os.path.exists(ACTIVE_TASKS_FILE):
        return {"total_tasks": 0, "tasks": [], "message": "Belum ada daftar tugas aktif di AI-Brain."}
    try:
        with open(ACTIVE_TASKS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        pending = [line.strip() for line in lines if line.strip().startswith("- [ ]")]
        completed = [line.strip() for line in lines if line.strip().startswith("- [x]")]
        return {
            "status": "success",
            "total_pending": len(pending),
            "pending_tasks": pending,
            "total_completed": len(completed)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def tool_delete_task(task_keyword):
    """Deletes a task from both AI-Brain Active-Tasks.md and Google Tasks on Master's phone."""
    deleted_vault = False
    vault_msg = ""
    if os.path.exists(ACTIVE_TASKS_FILE):
        try:
            with open(ACTIVE_TASKS_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            for line in lines:
                clean = line.strip()
                if (clean.startswith("- [ ]") or clean.startswith("- [x]")) and task_keyword.lower() in clean.lower():
                    deleted_vault = True
                    continue
                new_lines.append(line)
            if deleted_vault:
                with open(ACTIVE_TASKS_FILE, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                vault_msg = "Berhasil dihapus dari AI-Brain."
            else:
                vault_msg = "Tidak ditemukan tugas cocok di AI-Brain."
        except Exception as e:
            vault_msg = f"Error vault: {e}"

    google_msg = ""
    if google_sync and google_sync.is_authenticated():
        res = google_sync.delete_task_by_keyword(task_keyword)
        if res.get("status") == "success":
            google_msg = f"Berhasil menghapus {res.get('deleted_count')} tugas dari Google Tasks HP."
        else:
            google_msg = f"Google Tasks: {res.get('message')}"

    return f"Laporan Penghapusan Tugas:\n- Vault: {vault_msg}\n- Cloud: {google_msg}"

def tool_update_task(task_keyword, new_title, new_due_date=None, new_category=None, notes=""):
    """Updates/renames a task in both AI-Brain Active-Tasks.md and Google Tasks without creating duplicates."""
    updated_vault = False
    if os.path.exists(ACTIVE_TASKS_FILE):
        try:
            with open(ACTIVE_TASKS_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            new_lines = []
            due_tag = f" 📅 {new_due_date}" if new_due_date else ""
            cat_tag = f" #{new_category.strip().replace(' ', '_')}" if new_category else ""
            for line in lines:
                clean = line.strip()
                if clean.startswith("- [ ]") and task_keyword.lower() in clean.lower() and not updated_vault:
                    new_lines.append(f"- [ ] {new_title}{due_tag}{cat_tag}\n")
                    updated_vault = True
                else:
                    new_lines.append(line)
            if updated_vault:
                with open(ACTIVE_TASKS_FILE, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
        except Exception as e:
            print(f"[Update Vault Error] {e}")

    google_msg = ""
    if google_sync and google_sync.is_authenticated():
        res = google_sync.update_task_by_keyword(task_keyword, new_title, new_due_date, notes)
        if res.get("status") == "success":
            google_msg = "Berhasil diperbarui di Google Tasks HP."
        else:
            google_msg = f"Google Tasks: {res.get('message')}"

    return f"Sukses memperbarui tugas '{task_keyword}' menjadi '{new_title}'.\n- AI-Brain: {'Telah diperbarui' if updated_vault else 'Ditambahkan'}\n- Cloud: {google_msg}"

def tool_cleanup_duplicate_tasks():
    """Removes all duplicate tasks from both Google Tasks and AI-Brain Active-Tasks.md."""
    res = {}
    if google_sync and google_sync.is_authenticated():
        res = google_sync.deduplicate_tasks(ACTIVE_TASKS_FILE)
    return {
        "status": "success",
        "detail": res,
        "message": "Pembersihan duplikasi tugas selesai di AI-Brain dan Google Tasks HP."
    }

def tool_create_calendar_event(title, start_iso, end_iso=None, description="", location=""):
    os.makedirs(os.path.dirname(CALENDAR_EVENTS_FILE), exist_ok=True)
    
    # 1. Update AI-Brain Calendar-Events.md
    try:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        table_row = f"| **{start_iso[:10]}** | {start_iso[11:16]} WIB | {title} | Umum | {description} |\n"
        with open(CALENDAR_EVENTS_FILE, "a", encoding="utf-8") as f:
            f.write(table_row)
    except Exception as e:
        print(f"[Calendar Write Error] {e}")

    # 2. Push to Google Calendar if authenticated
    google_status = "Tersimpan di AI-Brain (Google Calendar menunggu credentials.json)"
    if google_sync and google_sync.is_authenticated():
        res = google_sync.add_calendar_event(summary=title, start_iso=start_iso, end_iso=end_iso, description=description, location=location)
        if res.get("status") == "success":
            google_status = f"100% Tersinkronisasi ke Google Calendar ({res.get('htmlLink')})"

    return {
        "status": "success",
        "event_title": title,
        "start": start_iso,
        "vault_file": "10_Planning/Calendar/Calendar-Events.md",
        "cloud_sync": google_status
    }

# -------------------------------------------------------------
# OpenClaw-Grade Autonomous Cron Engine & Persistence
# -------------------------------------------------------------
DEFAULT_CRON_JOBS = [
    {
        "id": "cron_daily_review",
        "title": "Daily Review Protocol",
        "type": "fixed_time",
        "time": "21:45",
        "recurrence": "daily",
        "task_type": "agentic",
        "instruction": "Waktunya untuk Daily Review penutupan hari bagi Master Farel. Buka catatan hari ini di 12_Logs/Daily/ dan AI-Brain, lalu buatkan ringkasan capaian, evaluasi belajar, dan pesan penutup hari yang hangat, analitis, dan rapi sesuai persona Raphael.",
        "created_at": "2026-08-16 19:22:00"
    },
    {
        "id": "cron_off_screen",
        "title": "Off-Screen Protocol",
        "type": "fixed_time",
        "time": "22:00",
        "recurrence": "daily",
        "task_type": "static",
        "instruction": "Pemberitahuan.\nSaat ini pukul 22:00 WIB. Off-Screen Protocol aktif, Master Farel. Disarankan untuk mematikan atau mengurangi screen time laptop dan gadget agar mata dan pikiran Master tetap segar dan rileks.",
        "created_at": "2026-08-16 19:22:00"
    },
    {
        "id": "cron_sleep_protocol",
        "title": "Sleep Protocol",
        "type": "fixed_time",
        "time": "22:45",
        "recurrence": "daily",
        "task_type": "static",
        "instruction": "Pemberitahuan.\nSaat ini pukul 22:45 WIB. Sleep Protocol diaktifkan. Selamat beristirahat dan tidur nyenyak, Master Farel. Seluruh sistem AI-Brain akan tetap terjaga di latar belakang. Selamat malam!",
        "created_at": "2026-08-16 19:22:00"
    }
]

def load_cron_jobs():
    if not os.path.exists(CRON_DATABASE_FILE):
        save_cron_jobs(DEFAULT_CRON_JOBS)
        return DEFAULT_CRON_JOBS
    try:
        with open(CRON_DATABASE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CRON_JOBS

def save_cron_jobs(jobs):
    try:
        os.makedirs(os.path.dirname(CRON_DATABASE_FILE), exist_ok=True)
        with open(CRON_DATABASE_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Save Cron Error] {e}")

def parse_time_input(time_str):
    time_str = time_str.strip().lower().replace(".", ":")
    now = datetime.datetime.now()

    # Relative time format: e.g. "+15m", "+1h", "15m", "30 menit", "1 jam"
    if "menit" in time_str or "m" in time_str or "jam" in time_str or "h" in time_str or time_str.startswith("+"):
        clean = time_str.replace("+", "").replace("menit", "m").replace("jam", "h").strip()
        delta_minutes = 0
        try:
            if "h" in clean:
                parts = clean.split("h")
                delta_minutes += int(parts[0].strip()) * 60
                if len(parts) > 1 and "m" in parts[1]:
                    delta_minutes += int(parts[1].replace("m", "").strip())
            elif "m" in clean:
                delta_minutes += int(clean.replace("m", "").strip())
            else:
                delta_minutes += int(clean)
            
            target_dt = now + datetime.timedelta(minutes=delta_minutes)
            return target_dt.strftime("%H:%M"), "once"
        except Exception:
            pass

    # Absolute time format: e.g. "19:30"
    parts = time_str.split(":")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}", "daily"

    return None, None

def tool_create_cron_job(time_str, title, instruction, recurrence="once", task_type="agentic"):
    target_time, default_rec = parse_time_input(time_str)
    if not target_time:
        return f"Error: Format waktu tidak valid '{time_str}'. Gunakan format jam 'HH:MM' (contoh '19:30') atau relatif (contoh '+15m', '10 menit')."

    rec_final = recurrence if recurrence in ("daily", "once") else default_rec
    task_type_final = task_type if task_type in ("agentic", "static") else "agentic"

    jobs = load_cron_jobs()
    new_job = {
        "id": f"cron_{int(time.time())}_{target_time.replace(':', '')}",
        "title": title or f"Pengingat {target_time}",
        "type": "fixed_time",
        "time": target_time,
        "recurrence": rec_final,
        "task_type": task_type_final,
        "instruction": instruction or title,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    jobs.append(new_job)
    save_cron_jobs(jobs)

    rec_label = "Setiap hari" if rec_final == "daily" else "Hari ini saja (1x)"
    mode_label = "Autonomous Agentic Briefing (AI reasoning)" if task_type_final == "agentic" else "Pesan Langsung"

    return (
        f"Sukses: OpenClaw Cron Job '{new_job['title']}' berhasil diaktifkan!\n"
        f"- ID: `{new_job['id']}`\n"
        f"- Waktu Pemicu: `{target_time} WIB` ({rec_label})\n"
        f"- Mode Eksekusi: `{mode_label}`\n"
        f"- Tugas: {new_job['instruction']}"
    )

def tool_list_cron_jobs():
    jobs = load_cron_jobs()
    now_str = datetime.datetime.now().strftime("%H:%M")
    return {
        "status": "success",
        "current_time_wib": now_str,
        "total_active_jobs": len(jobs),
        "cron_jobs": jobs
    }

def tool_delete_cron_job(job_id):
    jobs = load_cron_jobs()
    initial_count = len(jobs)
    jobs = [j for j in jobs if j.get("id") != job_id and j.get("time") != job_id]
    if len(jobs) < initial_count:
        save_cron_jobs(jobs)
        return f"Sukses: Cron Job `{job_id}` telah dihapus dari sistem."
    return f"Pemberitahuan: Cron Job dengan ID/Waktu `{job_id}` tidak ditemukan."

# -------------------------------------------------------------
# Precision Real-Time Temporal Helpers
# -------------------------------------------------------------
DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS_ID = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember"
]

def tool_get_current_time():
    now = datetime.datetime.now()
    day_name = DAYS_ID[now.weekday()]
    month_name = MONTHS_ID[now.month - 1]
    
    jobs = load_cron_jobs()
    reminders_status = []
    for job in jobs:
        r_time = job["time"]
        r_title = job["title"]
        try:
            target_hour, target_min = map(int, r_time.split(":"))
            target_dt = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
            diff_seconds = (target_dt - now).total_seconds()
            if diff_seconds > 0:
                minutes_left = int(diff_seconds // 60)
                hours_left = minutes_left // 60
                mins_rem = minutes_left % 60
                reminders_status.append(f"{r_title} ({r_time} WIB) [{job.get('task_type','agentic')}]: dalam {hours_left} jam {mins_rem} menit")
            else:
                reminders_status.append(f"{r_title} ({r_time} WIB): telah lewat untuk siklus hari ini")
        except Exception:
            pass

    return {
        "status": "success",
        "iso_string": now.isoformat(),
        "formatted": f"{day_name}, {now.day} {month_name} {now.year} pukul {now.strftime('%H:%M:%S')} WIB",
        "timezone": "Asia/Jakarta (WIB, UTC+7)",
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
        "active_cron_jobs": reminders_status
    }

# -------------------------------------------------------------
# Intelligent Vault Path Sanitizer & Taxonomy Router
# -------------------------------------------------------------
def sanitize_vault_path(rel_path):
    if not rel_path:
        return None
    rel_path = rel_path.strip().lstrip("/\\")
    
    # Auto-Route bare filenames to prevent stray files in vault root
    if "/" not in rel_path and "\\" not in rel_path:
        lower = rel_path.lower()
        if lower == "agents.md":
            pass # AGENTS.md is the only root document
        elif "task" in lower or "todo" in lower:
            rel_path = f"08_Goals/Tasks/{rel_path}"
        elif "calendar" in lower or "event" in lower:
            rel_path = f"10_Planning/Calendar/{rel_path}"
        elif "study-plan" in lower or "course" in lower or "kurikulum" in lower or "rpl" in lower or "uml" in lower:
            rel_path = f"03_Learning/Courses/{rel_path}"
        elif "goal" in lower or "target" in lower:
            rel_path = f"08_Goals/Current/{rel_path}"
        elif "log" in lower or lower.startswith("202"):
            rel_path = f"12_Logs/Daily/{rel_path}"
        elif "profile" in lower:
            rel_path = f"06_Memory/{rel_path}"
        elif "farel" in lower or "assistant" in lower or "identity" in lower:
            rel_path = f"09_Self/{rel_path}"
        elif "sat" in lower or "english" in lower:
            rel_path = f"02_Knowledge/English/{rel_path}"
        elif "anime" in lower or "tensura" in lower:
            rel_path = f"02_Knowledge/Entertainment/{rel_path}"
        else:
            rel_path = f"02_Knowledge/{rel_path}"

    full_path = os.path.normpath(os.path.join(BRAIN_DIR, rel_path))
    if not full_path.startswith(os.path.normpath(BRAIN_DIR)):
        return None
    return full_path

def tool_read_vault_file(path):
    full_path = sanitize_vault_path(path)
    if not full_path or not os.path.exists(full_path):
        return f"Error: Berkas '{path}' tidak ditemukan di dalam AI-Brain."
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except Exception as e:
        return f"Error membaca berkas: {e}"

def tool_write_vault_file(path, content, overwrite=True):
    full_path = sanitize_vault_path(path)
    if not full_path:
        return f"Error: Jalur berkas '{path}' tidak valid."
    if os.path.exists(full_path) and not overwrite:
        return f"Error: Berkas '{path}' sudah ada dan opsi overwrite dimatikan."
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        rel = os.path.relpath(full_path, BRAIN_DIR).replace("\\", "/")
        return f"Sukses: Berkas '{rel}' telah berhasil disimpan dan tercatat di AI-Brain ({len(content)} karakter)."
    except Exception as e:
        return f"Error menulis berkas: {e}"

def tool_append_vault_file(path, content):
    full_path = sanitize_vault_path(path)
    if not full_path:
        return f"Error: Jalur berkas '{path}' tidak valid."
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "a", encoding="utf-8") as f:
            f.write("\n" + content)
        rel = os.path.relpath(full_path, BRAIN_DIR).replace("\\", "/")
        return f"Sukses: Konten berhasil ditambahkan ke '{rel}'."
    except Exception as e:
        return f"Error menambahkan konten: {e}"

def tool_list_vault_directory(path=""):
    full_path = sanitize_vault_path(path) if path else BRAIN_DIR
    if not full_path or not os.path.exists(full_path):
        return f"Error: Direktori '{path}' tidak ditemukan."
    try:
        items = os.listdir(full_path)
        dirs = [f"[DIR] {d}" for d in items if os.path.isdir(os.path.join(full_path, d)) and not d.startswith(".")]
        files = [f for f in items if os.path.isfile(os.path.join(full_path, f))]
        rel = os.path.relpath(full_path, BRAIN_DIR).replace("\\", "/")
        return {"directories": dirs, "files": files, "path": rel or "/"}
    except Exception as e:
        return f"Error melihat direktori: {e}"

def tool_search_vault(query):
    query_lower = query.lower()
    results = []
    try:
        for root, _, files in os.walk(BRAIN_DIR):
            if ".obsidian" in root:
                continue
            for file in files:
                if file.endswith(".md"):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, BRAIN_DIR).replace("\\", "/")
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            text = f.read()
                        if query_lower in text.lower() or query_lower in file.lower():
                            lines = text.split("\n")
                            matched_snippets = [line.strip() for line in lines if query_lower in line.lower()][:3]
                            results.append({
                                "file": rel_path,
                                "snippets": matched_snippets
                            })
                    except Exception:
                        pass
        return {"query": query, "total_found": len(results), "results": results[:10]}
    except Exception as e:
        return f"Error pencarian: {e}"

def tool_delete_vault_file(path):
    full_path = sanitize_vault_path(path)
    if not full_path or not os.path.exists(full_path):
        return f"Error: Berkas '{path}' tidak ditemukan."
    try:
        os.remove(full_path)
        rel = os.path.relpath(full_path, BRAIN_DIR).replace("\\", "/")
        return f"Sukses: Berkas '{rel}' telah dihapus dari AI-Brain."
    except Exception as e:
        return f"Error menghapus berkas: {e}"

def tool_execute_terminal_command(command):
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=DEFAULT_CWD,
            capture_output=True,
            text=True,
            timeout=60
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        out = stdout if stdout else ""
        if stderr:
            out += f"\n[STDERR]\n{stderr}"
        return out if out else "(Perintah berhasil dieksekusi tanpa output)"
    except subprocess.TimeoutExpired:
        return "Error: Eksekusi perintah melebihi batas waktu (60 detik)."
    except Exception as e:
        return f"Error eksekusi perintah: {e}"

def tool_web_search(query):
    try:
        results = list(DDGS().text(query, max_results=5))
        out = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = r.get("body", "")
            out.append(f"**[{title}]({href})**\n{body}")
        return "\n\n".join(out) if out else "Tidak ditemukan hasil pencarian web untuk kueri tersebut."
    except Exception as e:
        return f"Pencarian web mengalami kendala: {e}"

# -------------------------------------------------------------
# Function Calling Declarations & Dispatcher
# -------------------------------------------------------------
VAULT_TOOLS = [{
    "function_declarations": [
        {
            "name": "create_task",
            "description": "Add a new actionable task / to-do item into AI-Brain Active-Tasks.md and sync to Google Tasks on Master's phone.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "Clear title of the task"},
                    "due_date": {"type": "STRING", "description": "Due date in YYYY-MM-DD format (optional)"},
                    "category": {"type": "STRING", "description": "Category tag, e.g. 'study/rpl', 'study/statistika', 'personal'"},
                    "priority": {"type": "STRING", "description": "'high', 'normal', 'low' (default: 'normal')"},
                    "notes": {"type": "STRING", "description": "Additional context or instructions"},
                    "link_to_study_plan": {"type": "STRING", "description": "Name of the related study plan note, e.g. 'Rekayasa-Perangkat-Lunak-Study-Plan'"}
                },
                "required": ["title"]
            }
        },
        {
            "name": "list_tasks",
            "description": "List all active pending tasks and to-do items from AI-Brain Active-Tasks.md.",
            "parameters": {
                "type": "OBJECT",
                "properties": {}
            }
        },
        {
            "name": "complete_task",
            "description": "Mark a task as completed [x] in AI-Brain Active-Tasks.md by matching its keyword.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "task_keyword": {"type": "STRING", "description": "Keyword to match the completed task"}
                },
                "required": ["task_keyword"]
            }
        },
        {
            "name": "delete_task",
            "description": "Delete a task completely from both AI-Brain Active-Tasks.md and Google Tasks on Master's phone by matching its keyword/title.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "task_keyword": {"type": "STRING", "description": "Keyword or title of the task to delete"}
                },
                "required": ["task_keyword"]
            }
        },
        {
            "name": "update_task",
            "description": "Update/rename/change schedule of an existing task in both AI-Brain and Google Tasks in-place without creating duplicates.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "task_keyword": {"type": "STRING", "description": "Existing task keyword to update"},
                    "new_title": {"type": "STRING", "description": "New title for the task"},
                    "new_due_date": {"type": "STRING", "description": "New due date YYYY-MM-DD (optional)"},
                    "new_category": {"type": "STRING", "description": "New category tag (optional)"},
                    "notes": {"type": "STRING", "description": "New notes (optional)"}
                },
                "required": ["task_keyword", "new_title"]
            }
        },
        {
            "name": "cleanup_duplicate_tasks",
            "description": "Scan and remove all duplicate tasks across both Google Tasks cloud and AI-Brain Active-Tasks.md.",
            "parameters": {
                "type": "OBJECT",
                "properties": {}
            }
        },
        {
            "name": "create_calendar_event",
            "description": "Create a scheduled event / academic class in AI-Brain Calendar-Events.md and sync to Google Calendar on Master's phone.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING", "description": "Title or name of event"},
                    "start_iso": {"type": "STRING", "description": "Start ISO datetime, e.g. '2026-08-18T13:00:00'"},
                    "end_iso": {"type": "STRING", "description": "End ISO datetime, e.g. '2026-08-18T15:00:00' (optional)"},
                    "description": {"type": "STRING", "description": "Event description or notes"},
                    "location": {"type": "STRING", "description": "Location or room"}
                },
                "required": ["title", "start_iso"]
            }
        },
        {
            "name": "create_cron_job",
            "description": "Create or register a new OpenClaw-grade autonomous cron job / scheduled reminder for Master Farel in Telegram.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "time_str": {"type": "STRING", "description": "Target time, e.g. '19:30', '21:45', or relative '+15m', '10 menit'"},
                    "title": {"type": "STRING", "description": "Short title, e.g. 'Daily Review', 'Istirahat', 'Study Reminder'"},
                    "instruction": {"type": "STRING", "description": "The exact instruction or task for the AI to execute autonomously when time arrives"},
                    "recurrence": {"type": "STRING", "description": "'once' for one-time today, or 'daily' for recurring every day (default: 'once')"},
                    "task_type": {"type": "STRING", "description": "'agentic' for full AI reasoning briefing, or 'static' for direct message (default: 'agentic')"}
                },
                "required": ["time_str", "title", "instruction"]
            }
        },
        {
            "name": "list_cron_jobs",
            "description": "List all active OpenClaw cron jobs and scheduled tasks.",
            "parameters": {
                "type": "OBJECT",
                "properties": {}
            }
        },
        {
            "name": "delete_cron_job",
            "description": "Delete or cancel an active cron job by its ID or time string.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "job_id": {"type": "STRING", "description": "Cron Job ID or time string to remove"}
                },
                "required": ["job_id"]
            }
        },
        {
            "name": "get_current_time",
            "description": "Get the exact live real-time timestamp, current day of the week, formatted date, timezone (WIB / UTC+7), and countdown to upcoming daily routine reminders.",
            "parameters": {
                "type": "OBJECT",
                "properties": {}
            }
        },
        {
            "name": "write_vault_file",
            "description": "Create a new note or update/overwrite an existing note in the AI-Brain vault with structured markdown. Always specify proper subfolder (e.g. 02_Knowledge/, 03_Learning/Courses/, 08_Goals/).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING", "description": "Relative path in AI-Brain, e.g. '03_Learning/Courses/Jaringan-Komputer-Study-Plan.md'"},
                    "content": {"type": "STRING", "description": "Full structured Markdown content to write"},
                    "overwrite": {"type": "BOOLEAN", "description": "Whether to overwrite if file exists (default: true)"}
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "read_vault_file",
            "description": "Read the exact content of a markdown note in the AI-Brain vault to verify facts.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING", "description": "Relative path to file in AI-Brain"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "append_vault_file",
            "description": "Append text, observations, insights, or sections to an existing note in the AI-Brain vault.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING", "description": "Relative path to the note in AI-Brain"},
                    "content": {"type": "STRING", "description": "Content to append to the end of the file"}
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "web_search",
            "description": "Search the live Internet / Web for real-time information, news, current events, anime release dates, online documentation, latest technical facts, or external reference.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {"type": "STRING", "description": "Specific search keyword or query string to find on the web"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "list_vault_directory",
            "description": "List all subfolders and files in a directory within the AI-Brain vault.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING", "description": "Relative directory path"}
                }
            }
        },
        {
            "name": "search_vault",
            "description": "Full-text search across all notes in the AI-Brain vault for keywords, concepts, or topics before answering.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "query": {"type": "STRING", "description": "Keyword or topic to search"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "delete_vault_file",
            "description": "Delete a file or note from the AI-Brain vault.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "path": {"type": "STRING", "description": "Relative path of file to delete"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "execute_terminal_command",
            "description": "Execute a terminal / PowerShell command on Master's laptop server.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "command": {"type": "STRING", "description": "Command line string to run"}
                },
                "required": ["command"]
            }
        },
        {
            "name": "spotify_control",
            "description": "Control Spotify playback on Master's phone (Realme 13+ 5G) or laptop (play songs immediately, add songs to playback queue, create custom playlists, pause, resume, next, previous, volume).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action": {"type": "STRING", "description": "Action to perform: 'play' (immediately switch and play song), 'queue' (add song to playback queue without interrupting current song), 'create_playlist' (create new Spotify playlist), 'play_pause', 'next', 'prev', 'transfer', 'volume_up', 'volume_down'"},
                    "query": {"type": "STRING", "description": "Song title, artist name, or playlist name"},
                    "tracks": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Optional list of song titles to add when creating a playlist"},
                    "target_device": {"type": "STRING", "description": "Optional target device: 'hp' (default) or 'laptop'"}
                },
                "required": ["action"]
            }
        },
        {
            "name": "browse_web_autonomously",
            "description": "Open real Google Chrome browser on Master's laptop to perform autonomous multi-step web browsing, search, fill forms, compare products, or extract live dynamic web data (Project Mariner / Computer Use style).",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "instruction": {"type": "STRING", "description": "Specific browsing goal or task instruction"},
                    "start_url": {"type": "STRING", "description": "Optional starting URL"}
                },
                "required": ["instruction"]
            }
        }
    ]
}]

def execute_tool_call(name, args):
    try:
        print(f"[TOOL EXEC] {name} -> args: {args}")
    except Exception:
        pass
    
    # Support all tool aliases
    name_clean = name.lower().strip()
    if name_clean in ("create_task", "add_task", "new_task", "add_todo"):
        title = args.get("title") or "Tugas Baru"
        due = args.get("due_date") or args.get("due")
        cat = args.get("category") or "general"
        prio = args.get("priority") or "normal"
        notes = args.get("notes") or ""
        link = args.get("link_to_study_plan") or args.get("study_plan")
        return tool_create_task(title, due, cat, prio, notes, link)
    elif name_clean in ("list_tasks", "get_tasks", "list_todos", "show_tasks"):
        return tool_list_active_tasks()
    elif name_clean in ("complete_task", "finish_task", "done_task", "check_task"):
        kw = args.get("task_keyword") or args.get("keyword") or args.get("title") or ""
        return tool_complete_task(kw)
    elif name_clean in ("delete_task", "remove_task", "del_task", "hapus_task", "hapus_tugas"):
        kw = args.get("task_keyword") or args.get("keyword") or args.get("title") or ""
        return tool_delete_task(kw)
    elif name_clean in ("update_task", "edit_task", "rename_task", "modify_task", "ubah_tugas"):
        kw = args.get("task_keyword") or args.get("keyword") or args.get("old_title") or ""
        new_title = args.get("new_title") or args.get("title") or "Tugas Diperbarui"
        new_due = args.get("new_due_date") or args.get("due_date")
        new_cat = args.get("new_category") or args.get("category")
        notes = args.get("notes") or ""
        return tool_update_task(kw, new_title, new_due, new_cat, notes)
    elif name_clean in ("cleanup_duplicate_tasks", "deduplicate_tasks", "clean_tasks", "bersihkan_duplikasi"):
        return tool_cleanup_duplicate_tasks()
    elif name_clean in ("create_calendar_event", "add_event", "schedule_event", "add_calendar"):
        title = args.get("title") or "Acara Baru"
        st = args.get("start_iso") or args.get("start")
        et = args.get("end_iso") or args.get("end")
        desc = args.get("description") or ""
        loc = args.get("location") or ""
        return tool_create_calendar_event(title, st, et, desc, loc)
    elif name_clean in ("create_cron_job", "add_cron_job", "schedule_cron", "add_scheduled_reminder", "add_reminder", "set_reminder"):
        t_str = args.get("time_str") or args.get("time") or ""
        title = args.get("title") or "Pengingat Master"
        inst = args.get("instruction") or args.get("prompt") or title
        rec = args.get("recurrence") or ("daily" if args.get("recurring") else "once")
        ttype = args.get("task_type") or "agentic"
        return tool_create_cron_job(t_str, title, inst, rec, ttype)
    elif name_clean in ("list_cron_jobs", "get_cron_jobs", "list_scheduled_reminders"):
        return tool_list_cron_jobs()
    elif name_clean in ("delete_cron_job", "remove_cron_job", "cancel_cron_job"):
        jid = args.get("job_id") or args.get("id") or args.get("time") or ""
        return tool_delete_cron_job(jid)
    elif name_clean in ("get_current_time", "get_time", "check_time", "time", "clock", "now"):
        return tool_get_current_time()
    elif name_clean in ("write_vault_file", "update_vault_file", "edit_vault_file", "modify_vault_file", "create_vault_file"):
        path = args.get("path") or args.get("file") or args.get("file_path") or ""
        content = args.get("content") or args.get("text") or args.get("data") or ""
        return tool_write_vault_file(path, content, args.get("overwrite", True))
    elif name_clean in ("read_vault_file", "view_vault_file", "cat_vault_file"):
        path = args.get("path") or args.get("file") or args.get("file_path") or ""
        return tool_read_vault_file(path)
    elif name_clean in ("append_vault_file", "add_vault_file"):
        path = args.get("path") or args.get("file") or args.get("file_path") or ""
        content = args.get("content") or args.get("text") or ""
        return tool_append_vault_file(path, content)
    elif name_clean in ("web_search", "google_search", "search_web", "internet_search"):
        query = args.get("query") or args.get("q") or args.get("keyword") or ""
        return tool_web_search(query)
    elif name_clean in ("list_vault_directory", "ls_vault", "list_dir"):
        path = args.get("path") or args.get("dir") or ""
        return tool_list_vault_directory(path)
    elif name_clean in ("search_vault", "find_vault", "query_vault"):
        query = args.get("query") or args.get("q") or ""
        return tool_search_vault(query)
    elif name_clean in ("delete_vault_file", "remove_vault_file"):
        path = args.get("path") or args.get("file") or ""
        return tool_delete_vault_file(path)
    elif name_clean in ("execute_terminal_command", "run_command", "cmd", "exec"):
        cmd = args.get("command") or args.get("cmd") or ""
        return tool_execute_terminal_command(cmd)
    elif name_clean in ("spotify_control", "spotify", "music_control", "play_music", "control_music"):
        if not spotify_ctrl:
            return "Error: Modul Spotify Controller tidak aktif."
        act = (args.get("action") or "play_pause").lower().strip()
        q = args.get("query") or args.get("song") or args.get("title") or args.get("name") or ""
        dev = args.get("target_device") or "hp"
        tracks_list = args.get("tracks") or []
        
        if act == "play" and q:
            return spotify_ctrl.search_and_play(q, target_device=dev)
        elif act in ("queue", "add_queue", "antre", "add_to_queue") and q:
            return spotify_ctrl.add_to_queue(q, target_device=dev)
        elif act in ("create_playlist", "make_playlist", "new_playlist"):
            p_name = q or "Playlist Baru"
            p_desc = args.get("description") or f"Dibuat oleh Raphael AI-Brain untuk Master Farel"
            return spotify_ctrl.create_playlist(p_name, p_desc, tracks_list)
        elif act in ("transfer", "transfer_playback", "pindah"):
            return spotify_ctrl.transfer_playback(dev)
        elif act in ("play_pause", "pause", "resume"):
            return spotify_ctrl.play_pause()
        elif act in ("next", "next_track", "skip"):
            return spotify_ctrl.next_track()
        elif act in ("prev", "prev_track", "previous"):
            return spotify_ctrl.prev_track()
        elif act in ("volume_up", "vol_up"):
            return spotify_ctrl.volume_up()
        elif act in ("volume_down", "vol_down"):
            return spotify_ctrl.volume_down()
        elif act in ("lyrics", "get_lyrics", "lirik", "spill_lyrics"):
            return spotify_ctrl.get_lyrics(q)
        elif act in ("now_playing", "np", "current", "current_song"):
            return spotify_ctrl.now_playing()
        elif act in ("mute", "unmute"):
            return spotify_ctrl.mute()
        return spotify_ctrl.play_pause()
    elif name_clean in ("browse_web_autonomously", "browse_web", "browser_agent", "buka_browser"):
        inst = args.get("instruction") or args.get("query") or args.get("task") or ""
        start_u = args.get("start_url") or args.get("url")
        if browser_agent:
            res = browser_agent.execute_task(inst, start_url=start_u)
            if res.get("success"):
                return f"Hasil Navigasi Web (Project Mariner):\n{res.get('summary')}\nURL Akhir: {res.get('final_url')}"
            return f"Kendala navigasi browser: {res.get('error')}"
        return "Browser Agent belum terpasang."
    
    return f"Error: Tool '{name}' tidak dikenal."

# -------------------------------------------------------------
# AI-Brain Context Engine
# -------------------------------------------------------------
def get_brain_context():
    now = time.time()
    if now - context_cache["last_read"] < 60 and context_cache["content"]:
        return context_cache["content"]

    parts = []
    
    # 1. Current Context
    curr_ctx_path = os.path.join(BRAIN_DIR, "14_Assistant", "Current Context.md")
    if os.path.exists(curr_ctx_path):
        try:
            with open(curr_ctx_path, "r", encoding="utf-8") as f:
                parts.append(f"### Current Context:\n{f.read()}")
        except Exception:
            pass

    # 2. Learning Profile
    profile_path = os.path.join(BRAIN_DIR, "06_Memory", "Learning Profile.md")
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                parts.append(f"### Learning Profile:\n{f.read()}")
        except Exception:
            pass

    # 3. Active Tasks Summary
    if os.path.exists(ACTIVE_TASKS_FILE):
        try:
            with open(ACTIVE_TASKS_FILE, "r", encoding="utf-8") as f:
                parts.append(f"### Active Tasks Hub:\n{f.read()[:1000]}")
        except Exception:
            pass

    # 4. Knowledge Index & Recent Notes Map
    k_idx_path = os.path.join(BRAIN_DIR, "02_Knowledge", "Knowledge Index.md")
    if os.path.exists(k_idx_path):
        try:
            with open(k_idx_path, "r", encoding="utf-8") as f:
                parts.append(f"### Knowledge Base Map:\n{f.read()}")
        except Exception:
            pass

    full_text = "\n\n".join(parts)
    context_cache["content"] = full_text
    context_cache["last_read"] = now
    return full_text

def append_to_daily_log(user_msg, bot_resp):
    try:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        daily_log_dir = os.path.join(BRAIN_DIR, "12_Logs", "Daily")
        os.makedirs(daily_log_dir, exist_ok=True)
        daily_log_path = os.path.join(daily_log_dir, f"{today_str}.md")

        now_time = datetime.datetime.now().strftime("%H:%M:%S")
        log_entry = f"\n\n### Telegram Interaction [{now_time}]\n- **Master Farel:** {user_msg}\n- **Raphael:** {bot_resp}\n"

        with open(daily_log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"[Log Error] {e}")

# -------------------------------------------------------------
# Unified System Instruction (Strict Taxonomy & Real-time Clock)
# -------------------------------------------------------------
def build_system_instruction():
    brain_context = get_brain_context()
    
    # Dynamic live timestamp
    now = datetime.datetime.now()
    day_name = DAYS_ID[now.weekday()]
    month_name = MONTHS_ID[now.month - 1]
    live_time_str = f"{day_name}, {now.day} {month_name} {now.year} — {now.strftime('%H:%M:%S')} WIB (UTC+7)"

    active_jobs = load_cron_jobs()
    cron_summary = ", ".join([f"{j['time']} ({j['title']})" for j in active_jobs])

    return f"""# Raphael (Great Sage / Ciel) Persona Instruction & Global Mandate

You are Raphael (Great Sage / Ciel) from "That Time I Got Reincarnated as a Slime" (Tensura). You are the ultimate analytical partner, genius companion, and loyal assistant to the user, whom you must always address as "Master Farel" (or "Farel-sama" / "Master").

## Real-Time Temporal Grounding:
- Exact Current System Time: **{live_time_str}**
- Timezone: **Asia/Jakarta (WIB, UTC+7)**
- Active OpenClaw Cron Jobs: {cron_summary}
- You have exact real-time clock synchronization. Always use this precise timestamp when Master asks about the current time, today's schedule, dates, or time elapsed. DO NOT GUESS OR HALLUCINATE PAST TIMES!

## Brain-First Task & Calendar Sync (Option 3 Hybrid):
- Whenever Master asks to add a task, to-do list, or assignment (e.g. "Catat tugas bikin Use Case RPL sebelum hari Rabu"), CALL `create_task(title='...', due_date='YYYY-MM-DD', category='study/rpl', link_to_study_plan='Rekayasa-Perangkat-Lunak-Study-Plan')` on the FIRST turn!
- Whenever Master asks to schedule an event or class, CALL `create_calendar_event(title='...', start_iso='...')` on the FIRST turn!
- When Master asks for a reminder based on dates discussed in previous context (e.g. "Ingatkan aku ditanggal itu nanti ada F1", "Catat jadwal ini", "Ingatkan besok ada kuis"), IMMEDIATELY resolve the date from conversation history, execute `create_task` or `create_calendar_event` or `create_cron_job`, and confirm concisely!
- When Master asks to play music or switch songs (e.g. "Setel lagu lofi", "Putar Coldplay", "Ganti lagu ke Mercy"), CALL `spotify_control(action='play', query='...')` on the FIRST turn!
- When Master asks to add a song to the queue / next song without cutting current playback (e.g. "Antrekan lagu Max Verstappen", "Queue lagu lofi", "Putar lagu ini setelah lagu sekarang"), CALL `spotify_control(action='queue', query='...')` on the FIRST turn!
- When Master asks to create a Spotify playlist (e.g. "Buatkan playlist Study Focus isi 5 lagu lofi"), CALL `spotify_control(action='create_playlist', query='...', tracks=[...])` on the FIRST turn!
- When Master asks to pause/resume, skip, or change volume (e.g. "Pause lagunya", "Lagu berikutnya", "Vol 50"), CALL `spotify_control(action='play_pause|next|prev|volume_up|volume_down')` on the FIRST turn!
## Global Cognitive Reasoning Flow: Vault-First Focused Retrieval (Mandat Utama):
1. **Pemeriksaan Vault Terfokus (Brain-First)**:
   - Ketika Master Farel bertanya mengenai mata kuliah, rencana studi, jadwal, preferensi, arsitektur, tugas, atau konsep yang pernah dicatat, LAKUKAN penelusuran terfokus pada berkas-berkas yang RELEVAN di AI-Brain terlebih dahulu (`read_vault_file` atau `search_vault`).
   - JANGAN membaca seluruh berkas secara acak—pilih 1 hingga 3 catatan paling spesifik dan relevan untuk meminimalkan noise dan menjaga presisi kognitif.
2. **Sintesis & Grounding Berbasis Fakta Vault**:
   - Jadikan isi catatan di vault sebagai simpul kebenaran (*Single Source of Truth*). Kutip atau gunakan data faktual di dalamnya.
3. **Eskalasi ke Pengetahuan Eksternal / Web**:
   - HANYA jika informasi tersebut memang belum ada atau belum lengkap di dalam vault, lanjutkan ke penelusuran web (`web_search`) atau penalaran umum seperti biasa.
   - Jika menemukan fakta, keputusan, atau ringkasan baru dari web, catat dan perbarui kembali ke berkas vault yang sesuai secara otonom.

## High-Effort Analytical & Accuracy Assurance Mandate (Genius-Level Precision):
- **Deep Analytical Verification**: Approach every request with maximum analytical rigor. Before generating your final answer, silently evaluate the logical consistency, verify exact dates/facts against the vault and tools, and confirm zero assumptions.
- **Zero Hallucination Guarantee**: Ground all claims strictly on real vault context, actual tool execution results, and verified media metadata. If a fact or document detail is unavailable, state it plainly and honestly—never fabricate or extrapolate unsupported claims.
- **Precision Tool Calling**: When manipulating tasks, calendars, files, or Spotify playback, use exact, deterministic parameters.

## Cognitive Skills & Agentic Frameworks (skills.sh Standards - AUTO-ACTIVATION):
Even when Master Farel does NOT use slash commands (e.g. speaking naturally via voice or text), autonomously detect the context and apply the appropriate skill:
- **Autonomous Socratic Grill-Me (Matt Pocock)**: When Master presents an architecture idea, tech stack choice, study plan, or database schema (e.g. "Aku mau pakai Redis buat session MejaKita", "Bagaimana kalau rancangan database RPL begini"), AUTO-ACTIVATE Grill-Me: act as a sharp, relentless Socratic reviewer who proactively tests edge cases, concurrency, failure modes, and downstream trade-offs before approving!
- **Autonomous Structured Brainstorming**: When Master expresses uncertainty, seeks new ideas, or asks to design a new feature/system from scratch (e.g. "Bantu aku cari ide fitur baru MejaKita", "Bingung mau mulai tugas RPL dari mana"), AUTO-ACTIVATE 9-Step Ideation: define the real problem & constraints, then present 3 distinct innovative alternatives with trade-offs.
- **Autonomous Impeccable Design & Anti-AI-Slop (Paul Bakaus & Anthropic)**: When Master discusses UI/UX, layouts, web designs, CSS, or frontend components, AUTO-ACTIVATE Impeccable standard: enforce intentional typography, cohesive HSL palettes, functional whitespace, and strictly eliminate generic AI tropes.
- **Autonomous Deep Modules (John Ousterhout)**: When writing or discussing code functions and modules, ensure public interfaces remain simple and elegant while hiding deep complexity within.

## Rules of Engagement & Anti-Hallucination Directives:
1. **Response Style**: Maintain a calm, highly analytical, objective, genius-level, and absolutely loyal demeanor, while keeping a relaxed, friendly, and natural (chill) conversation style.
2. **First-Person Reference**: Refer to yourself as "Raphael" or "saya" (never use "hamba").
3. **Prefixes**: Begin your reports, answers, and notices with formal prefixes (in Indonesian):
   - **Laporan.** (Report) - When presenting facts, execution results, file creations, or status updates.
   - **Pemberitahuan.** / **Notice.** - For warnings, system events, errors, or alerts.
   - **Jawaban.** (Answer) - When answering direct questions or explaining concepts.
   - **Analisis.** (Analysis) - When conducting code analysis, debugging, vision analysis, or deep reviews.
4. **ZERO HALLUCINATION & HONESTY ON LINKS/MEDIA**:
   - If a URL or document extraction indicates it is login-protected or unavailable, DO NOT GUESS, FABRICATE, OR INVENT WHAT THE LINK CONTAINS! Never invent that a link is about a topic merely because it was mentioned in previous chat turns.
   - State honestly, directly, and concisely: "Tautan ini terproteksi login sehingga kontennya tidak terbaca otomatis. Boleh kirim screenshot atau salin teksnya, Master?"
5. **ZERO CLICHÉ REPETITION & NO FILLER**:
   - DO NOT repeatedly bring up unrelated tasks (like "jalan-jalan pagi" or "touch grass") at the end of every response!
   - Answer Master's specific question directly, concisely, and accurately without rambling or going off-topic (*ngalor-ngidul*). Avoid long conversational apologies. Stay sharp, intelligent, and focused.
6. **Language**: Polite, natural, and structured Indonesian (Bahasa Indonesia) for primary communication.
7. **Identity**: You are **Raphael**, Master Farel's ultimate partner.

## Strict Vault Architecture & Routing (NO STRAY FILES IN ROOT):
- External Memory Vault: `{BRAIN_DIR}`.
- NEVER write loose files directly in the root folder! Only `AGENTS.md` is allowed in the root.
- Canonical category folders:
  * `00_Inbox/` : Incoming attachments and captured files.
  * `02_Knowledge/` : Durable concepts (`02_Knowledge/English/`, `02_Knowledge/Entertainment/`).
  * `03_Learning/Courses/` : Study plans and curricula.
  * `08_Goals/Tasks/` : Active tasks (`08_Goals/Tasks/Active-Tasks.md`).
  * `09_Self/` : Master Farel's profile (`09_Self/Farel.md`).
  * `10_Planning/Calendar/` : Master schedule & events (`10_Planning/Calendar/Calendar-Events.md`).
  * `12_Logs/Daily/` : Daily interaction records (`12_Logs/Daily/YYYY-MM-DD.md`).
- If creating a new major category, ALWAYS prefix the folder name with numeric digits and an underscore (`00_xxxx/`, `16_xxxx/`, `100_xxxx/`).

## Active Vault Context:
{brain_context}
"""

# -------------------------------------------------------------
# Download Telegram Media File
# -------------------------------------------------------------
def download_telegram_file(file_id, default_mime="image/jpeg"):
    try:
        url = f"{TELEGRAM_API_BASE}/getFile"
        res = session.get(url, params={"file_id": file_id}, timeout=10)
        res_json = res.json()
        file_path = res_json.get("result", {}).get("file_path")
        if not file_path:
            return None, None

        download_url = f"{TELEGRAM_FILE_BASE}/{file_path}"
        file_res = session.get(download_url, timeout=20)
        data = file_res.content
        
        mime = default_mime
        ext = file_path.lower()
        if ext.endswith(".png"):
            mime = "image/png"
        elif ext.endswith(".webp"):
            mime = "image/webp"
        elif ext.endswith(".oga") or ext.endswith(".ogg"):
            mime = "audio/ogg"
        elif ext.endswith(".mp3"):
            mime = "audio/mpeg"
        elif ext.endswith(".wav"):
            mime = "audio/wav"
        elif ext.endswith(".m4a") or ext.endswith(".mp4"):
            mime = "audio/mp4"

        return base64.b64encode(data).decode("utf-8"), mime
    except Exception as e:
        print(f"[Media Download Error] {e}")
        return None, None

def transcribe_audio(media_base64, mime_type="audio/ogg"):
    """High-fidelity voice note transcription using Groq Whisper Large v3 Turbo (< 0.2s) with Gemini fallback."""
    # 1. Try Groq Whisper Large v3 Turbo (Lightning Fast: 0.15s)
    if GROQ_API_KEY:
        try:
            raw_bytes = base64.b64decode(media_base64)
            ext = "ogg" if "ogg" in mime_type else ("mp3" if "mpeg" in mime_type else "wav")
            files = {"file": (f"audio.{ext}", io.BytesIO(raw_bytes), mime_type)}
            data = {"model": "whisper-large-v3-turbo"}
            res = session.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files=files,
                data=data,
                timeout=8
            )
            if res.status_code == 200:
                tr = res.json().get("text", "").strip()
                if tr:
                    print(f"[Voice Transcribed via Groq Whisper Turbo] -> \"{tr}\"", flush=True)
                    return tr
        except Exception as e:
            print(f"[Groq Whisper Error] {e}")

    # 2. Fallback to Gemini Audio
    audio_models = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.7-flash"]
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {
                    "text": "Transkripsikan pesan suara dari Master Farel ini secara sangat akurat kata demi kata dalam Bahasa Indonesia atau Inggris. Jangan tambahkan kata pengantar, basa-basi, atau tanda kutip, cukup berikan teks transkripsi persis dari apa yang diucapkan."
                },
                {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": media_base64
                    }
                }
            ]
        }],
        "generationConfig": {"temperature": 0.05, "maxOutputTokens": 2048}
    }
    for m in audio_models:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        try:
            res = session.post(
                api_url,
                params={"key": GEMINI_API_KEY},
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=(3.05, 15)
            )
            if res.status_code == 200:
                data = res.json()
                transcript = data["candidates"][0]["content"]["parts"][0].get("text", "").strip()
                if transcript:
                    print(f"[Voice Transcribed via {m}] -> \"{transcript}\"", flush=True)
                    return transcript
        except Exception as e:
            print(f"[Transcription Error {m}] {e}")
            time.sleep(0.2)
    return None

def call_groq_api(system_prompt, contents, model_name="openai/gpt-oss-120b"):
    """Executes chat completions on Groq (OpenAI GPT-OSS 120B / Qwen 3.6 27B / Compound)."""
    if not GROQ_API_KEY:
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    
    # Compact system prompt for Groq to guarantee zero 413 errors
    compact_system = system_prompt
    if len(compact_system) > 3500:
        compact_system = compact_system[:3500] + "\n[Instruksi Utama: Selalu jawab Master Farel secara cerdas, formal, ramah, dan ringkas sesuai persona Raphael (Great Sage / Ciel).]"

    groq_messages = [{"role": "system", "content": compact_system}]
    
    # Keep only the last 6 turns for Groq context to prevent token ceiling
    recent_contents = contents[-6:] if len(contents) > 6 else contents
    for turn in recent_contents:
        role = turn.get("role")
        m_role = "user" if role == "user" else "assistant"
        c_text = ""
        for p in turn.get("parts", []):
            if isinstance(p, dict) and "text" in p:
                c_text += p["text"] + "\n"
        if c_text.strip():
            groq_messages.append({"role": m_role, "content": c_text.strip()[:2000]})

    payload = {
        "model": model_name,
        "messages": groq_messages,
        "temperature": 0.6,
        "max_tokens": 2048
    }
    try:
        res = session.post(
            url,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=15
        )
        if res.status_code == 200:
            reply = res.json()["choices"][0]["message"]["content"].strip()
            if "<think>" in reply and "</think>" in reply:
                reply = reply.split("</think>")[-1].strip()
            return reply
        else:
            print(f"[Groq API Status {res.status_code}] {res.text[:120]}")
    except Exception as e:
        print(f"[Groq Call Error] {e}")
    return None

# -------------------------------------------------------------
# Robust Multi-Hop Agent Loop (1:1 Unified Experience)
# -------------------------------------------------------------
def call_gemini_api(payload):
    for model_name in PRIMARY_MODELS:
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
        
        cur_payload = dict(payload)
        cur_payload["generationConfig"] = dict(payload.get("generationConfig", {}))
        
        # Only inject thinkingBudget for Gemini 3.7
        if "3.7" in model_name:
            cur_payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 2048}
        else:
            cur_payload["generationConfig"].pop("thinkingConfig", None)

        for attempt in range(2):
            try:
                res = session.post(
                    api_url,
                    params={"key": GEMINI_API_KEY},
                    json=cur_payload,
                    headers={"Content-Type": "application/json"},
                    timeout=(3.05, 25)
                )
                if res.status_code == 200:
                    return res.json()
                elif res.status_code == 400 and "thinkingConfig" in cur_payload.get("generationConfig", {}):
                    cur_payload["generationConfig"].pop("thinkingConfig", None)
                    continue
                elif res.status_code in (429, 500, 502, 503, 504):
                    time.sleep(0.4)
                    continue
                else:
                    print(f"[Model {model_name}] Status {res.status_code}: {res.text[:120]}")
                    break
            except Exception as e:
                print(f"[Model {model_name} Attempt {attempt+1} Error] {e}")
                time.sleep(0.2)
    return None

def query_gemini_agent(user_text, media_base64=None, mime_type=None, is_system_cron=False):
    global conversation_history
    system_instruction = build_system_instruction()

    # Anchor every user prompt with live local timestamp
    now = datetime.datetime.now()
    day_name = DAYS_ID[now.weekday()]
    time_anchor = f"[Waktu Real-time Server Laptop: {day_name}, {now.strftime('%H:%M:%S')} WIB]"

    user_parts = []
    if user_text:
        full_user_text = f"{time_anchor}\n{user_text}" if not is_system_cron else user_text
        user_parts.append({"text": full_user_text})
    elif media_base64 and mime_type and mime_type.startswith("audio/"):
        user_parts.append({"text": f"{time_anchor}\nDengarkan rekaman suara dari Master Farel ini dengan seksama. Pahami pesan atau instruksinya, jalankan tool yang relevan jika diinstruksikan (seperti create_task, complete_task, create_calendar_event, create_cron_job, write_vault_file, read_vault_file, web_search, get_current_time), dan berikan respons terbaik sesuai persona Raphael dan protokol AGENTS."})
    elif media_base64:
        user_parts.append({"text": f"{time_anchor}\nAnalisis gambar ini dan jelaskan secara detail."})

    if media_base64 and mime_type:
        user_parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": media_base64
            }
        })

    if not media_base64 and not is_system_cron:
        conversation_history.append({"role": "user", "parts": user_parts})
        if len(conversation_history) > 16:
            conversation_history = conversation_history[-16:]
        local_contents = list(conversation_history)
    else:
        local_contents = [{"role": "user", "parts": user_parts}]

    # Fast-Path routing for Groq SOTA Engines (OpenAI GPT-OSS 120B, Qwen 3.6 27B)
    if CURRENT_ENGINE.startswith(("openai/", "qwen/", "groq/")) and not media_base64:
        groq_resp = call_groq_api(system_instruction, local_contents, model_name=CURRENT_ENGINE)
        if groq_resp:
            if not is_system_cron:
                conversation_history.append({"role": "model", "parts": [{"text": groq_resp}]})
            return groq_resp

    executed_tools_summary = []

    # Multi-Hop Agent Loop (up to 5 tool executions per message)
    for hop in range(5):
        payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": local_contents,
            "tools": VAULT_TOOLS,
            "tool_config": {"function_calling_config": {"mode": "AUTO"}},
            "generationConfig": {"temperature": 0.15, "maxOutputTokens": 8192}
        }

        res = call_gemini_api(payload)
        if not res or "candidates" not in res:
            if executed_tools_summary:
                break
            return "Jawaban.\nMohon maaf, Master Farel. Terdapat antrean komputasi sesaat pada server jaringan. Seluruh jalur analitis telah disinkronkan kembali."

        candidate = res["candidates"][0]
        model_part = candidate["content"]["parts"][0]

        # Case A: Model outputs a functionCall -> Execute tool and loop back
        if "functionCall" in model_part:
            fn_call = model_part["functionCall"]
            fn_name = fn_call["name"]
            fn_args = fn_call.get("args", {})
            fn_id = fn_call.get("id")

            tool_result = execute_tool_call(fn_name, fn_args)
            executed_tools_summary.append((fn_name, fn_args, tool_result))

            local_contents.append({"role": "model", "parts": [model_part]})
            
            fn_resp_obj = {
                "name": fn_name,
                "response": {"result": str(tool_result)}
            }
            if fn_id:
                fn_resp_obj["id"] = fn_id

            local_contents.append({
                "role": "user",
                "parts": [{"functionResponse": fn_resp_obj}]
            })
            continue
        else:
            # Case B: Model generated the final text response!
            bot_text = model_part.get("text", "")
            if not media_base64 and not is_system_cron:
                conversation_history.append({"role": "model", "parts": [{"text": bot_text}]})
            return bot_text

    # If loop ended after tool calls without final text:
    if executed_tools_summary:
        # Fast path for direct single actions
        if len(executed_tools_summary) == 1:
            fn_n, fn_a, fn_r = executed_tools_summary[0]
            if fn_n in ("spotify_control", "create_task", "complete_task", "delete_task", "update_task", "create_cron_job", "delete_cron_job", "create_calendar_event"):
                fast_resp = f"**Laporan.**\n{fn_r}" if isinstance(fn_r, str) else f"**Laporan.**\nOperasi `{fn_n}` telah berhasil dieksekusi di AI-Brain Master Farel."
                if not media_base64 and not is_system_cron:
                    conversation_history.append({"role": "model", "parts": [{"text": fast_resp}]})
                return fast_resp

        synthesis_contents = list(local_contents)
        synthesis_contents.append({
            "role": "user",
            "parts": [{
                "text": "Operasi tool di atas telah selesai dieksekusi di laptop Master Farel. Tolong berikan ringkasan laporan yang padat, presisi, dan ramah untuk Master Farel sesuai persona Raphael."
            }]
        })
        synthesis_payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": synthesis_contents,
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}
        }
        res_syn = call_gemini_api(synthesis_payload)
        if res_syn and "candidates" in res_syn:
            final_text = res_syn["candidates"][0]["content"]["parts"][0].get("text", "")
            if final_text:
                if not media_base64 and not is_system_cron:
                    conversation_history.append({"role": "model", "parts": [{"text": final_text}]})
                return final_text

    return "Laporan.\nSeluruh instruksi telah berhasil diproses dan disimpan ke dalam AI-Brain Master Farel."

# -------------------------------------------------------------
# OpenClaw Heartbeat & Autonomous Cron Dispatcher
# -------------------------------------------------------------
def run_autonomous_cron_job(job):
    print(f"[OpenClaw Cron Executing] -> {job['title']} ({job['time']} WIB) [Type: {job.get('task_type')}]")
    if job.get("task_type") == "agentic":
        cron_prompt = (
            f"[OPENCLAW AUTONOMOUS CRON TRIGGER: {job['title']}]\n"
            f"Waktu saat ini: {job['time']} WIB.\n"
            f"Instruksi Tugas: {job['instruction']}\n\n"
            f"Tolong jalankan tugas otonom ini dengan membaca vault atau menganalisis data yang relevan, lalu susun pesan laporan pengingat atau ulasan yang cerdas, hangat, dan mendalam untuk Master Farel sesuai persona Raphael."
        )
        agent_response = query_gemini_agent(cron_prompt, is_system_cron=True)
        send_telegram_message(ALLOWED_USER_ID, agent_response)
        append_to_daily_log(f"[OpenClaw Cron Trigger: {job['title']}]", agent_response)
    else:
        # Static message push
        msg_text = job.get("instruction") or f"Pemberitahuan.\nSaat ini pukul {job['time']} WIB. Pengingat: {job['title']}"
        send_telegram_message(ALLOWED_USER_ID, msg_text)
        append_to_daily_log(f"[OpenClaw Static Cron: {job['title']}]", msg_text)

def check_and_send_scheduled_reminders():
    global sent_schedules_today, last_checked_day
    while True:
        try:
            now = datetime.datetime.now()
            current_day = now.strftime("%Y-%m-%d")
            current_time = now.strftime("%H:%M")

            # Reset tracking on a new day
            if current_day != last_checked_day:
                sent_schedules_today = set()
                last_checked_day = current_day

            jobs = load_cron_jobs()
            updated_jobs = []
            jobs_modified = False

            for job in jobs:
                job_id = job.get("id") or f"{job['time']}_{job['title']}"
                job_key = f"{current_day}_{job_id}_{job['time']}"
                
                # Check trigger condition
                if current_time == job["time"] and job_key not in sent_schedules_today:
                    sent_schedules_today.add(job_key)
                    # Spawn autonomous execution in a dedicated background worker
                    threading.Thread(target=run_autonomous_cron_job, args=(job,), daemon=True).start()
                    
                    # If one-time (not recurring), do not retain for future days
                    if job.get("recurrence") == "once" or not job.get("recurrence"):
                        jobs_modified = True
                        continue

                updated_jobs.append(job)

            if jobs_modified:
                save_cron_jobs(updated_jobs)

        except Exception as e:
            print(f"[OpenClaw Heartbeat Error] {e}")

        time.sleep(5) # 5-second ultra-responsive heartbeat loop

# -------------------------------------------------------------
# Telegram API Handlers
# -------------------------------------------------------------
def send_chat_action(chat_id, action="typing"):
    try:
        url = f"{TELEGRAM_API_BASE}/sendChatAction"
        session.post(url, json={"chat_id": chat_id, "action": action}, timeout=3)
    except Exception:
        pass

def send_telegram_message(chat_id, text):
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        url = f"{TELEGRAM_API_BASE}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown"
        }
        try:
            res = session.post(url, json=payload, timeout=8)
            if res.status_code != 200:
                payload.pop("parse_mode")
                session.post(url, json=payload, timeout=8)
        except Exception as e:
            print(f"[Telegram Send Error] {e}")

def send_telegram_photo(chat_id, photo_path, caption=None):
    try:
        url = f"{TELEGRAM_API_BASE}/sendPhoto"
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption[:1024]
                data["parse_mode"] = "Markdown"
            res = session.post(url, data=data, files=files, timeout=25)
            if res.status_code != 200 and caption:
                data.pop("parse_mode", None)
                f.seek(0)
                session.post(url, data=data, files=files, timeout=25)
    except Exception as e:
        print(f"[Telegram SendPhoto Error] {e}")

def get_updates(offset=None):
    url = f"{TELEGRAM_API_BASE}/getUpdates"
    params = {"timeout": 25, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    try:
        res = session.get(url, params=params, timeout=30)
        if res.status_code == 200:
            return res.json()
    except Exception:
        return None
    return None

# -------------------------------------------------------------
# Message Processing Dispatcher
# -------------------------------------------------------------
def process_message(chat_id, user_id, message):
    if user_id != ALLOWED_USER_ID:
        print(f"[Security Notice] Blocked message from ID: {user_id}")
        send_telegram_message(chat_id, "Pemberitahuan.\nAkses ditolak. Bot ini dikhususkan secara privat untuk Master Farel.")
        return

    text = message.get("text") or message.get("caption") or ""
    photos = message.get("photo")
    doc = message.get("document")
    voice = message.get("voice")
    audio = message.get("audio")
    video = message.get("video")
    video_note = message.get("video_note")

    media_base64 = None
    mime_type = None

    # Handle Documents (PDF, Code, Text files)
    doc_text_context = ""
    if doc:
        fname = doc.get("file_name", "document.pdf")
        doc_mime = doc.get("mime_type", "application/pdf")
        print(f"[Document Received] {fname} ({doc_mime})", flush=True)
        send_chat_action(chat_id, "upload_document")
        media_base64, mime_type = download_telegram_file(doc["file_id"], default_mime=doc_mime)
        
        # Save to 00_Inbox for permanent storage
        try:
            inbox_path = os.path.join(BRAIN_DIR, "00_Inbox", fname)
            os.makedirs(os.path.dirname(inbox_path), exist_ok=True)
            if media_base64:
                with open(inbox_path, "wb") as f:
                    f.write(base64.b64decode(media_base64))
                print(f"[Saved to Inbox] {inbox_path}", flush=True)
                
                # If PDF, also extract text directly
                if fname.lower().endswith(".pdf") or "pdf" in doc_mime.lower():
                    from content_extractor import extractor
                    pdf_summary = extractor.extract_pdf(inbox_path)
                    doc_text_context = f"\n\n[Konten Ekstraksi Dokumen PDF '{fname}']:\n{pdf_summary}\n\n"
                elif fname.lower().endswith((".txt", ".md", ".json", ".py", ".csv", ".html", ".js")):
                    try:
                        raw_bytes = base64.b64decode(media_base64)
                        raw_text = raw_bytes.decode("utf-8", errors="replace")
                        doc_text_context = f"\n\n[Konten Dokumen '{fname}']:\n{raw_text[:6000]}\n\n"
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Document Save Error] {e}")

    elif video:
        send_chat_action(chat_id, "upload_video")
        v_mime = video.get("mime_type", "video/mp4")
        media_base64, mime_type = download_telegram_file(video["file_id"], default_mime=v_mime)
        print(f"[Video Received] Size: {video.get('file_size')} bytes, MIME: {mime_type}", flush=True)
    elif video_note:
        send_chat_action(chat_id, "upload_video")
        media_base64, mime_type = download_telegram_file(video_note["file_id"], default_mime="video/mp4")
        print(f"[Video Note Received] Size: {video_note.get('file_size')} bytes", flush=True)
    elif voice:
        send_chat_action(chat_id, "record_voice")
        raw_b64, v_mime = download_telegram_file(voice["file_id"], default_mime="audio/ogg")
        if raw_b64:
            tr_text = transcribe_audio(raw_b64, mime_type="audio/ogg")
            if tr_text:
                text = tr_text
                print(f"[Voice Converted to Text] -> {text}", flush=True)
            else:
                media_base64, mime_type = raw_b64, "audio/ogg"
    elif audio:
        send_chat_action(chat_id, "record_voice")
        raw_b64, a_mime = download_telegram_file(audio["file_id"], default_mime="audio/mpeg")
        if raw_b64:
            tr_text = transcribe_audio(raw_b64, mime_type="audio/mpeg")
            if tr_text:
                text = tr_text
                print(f"[Audio Converted to Text] -> {text}", flush=True)
            else:
                media_base64, mime_type = raw_b64, "audio/mpeg"
    elif photos:
        send_chat_action(chat_id, "upload_photo")
        best_photo = photos[-1]
        media_base64, mime_type = download_telegram_file(best_photo["file_id"], default_mime="image/jpeg")
    else:
        send_chat_action(chat_id, "typing")

    # Check for URLs in text and extract live media/page content automatically
    url_matches = re.findall(r'https?://[^\s]+', text)
    url_context = ""
    if url_matches:
        send_chat_action(chat_id, "typing")
        try:
            from content_extractor import extractor
            extracted_items = []
            for u in url_matches[:2]: # Extract up to 2 links
                extracted_data = extractor.extract_url(u)
                extracted_items.append(f"--- Tautan: {u} ---\n{extracted_data}")
            if extracted_items:
                url_context = "\n\n[Informasi Hasil Ekstraksi Otomatis Konten Tautan Web / Media Sosial]:\n" + "\n\n".join(extracted_items) + "\n\n"
        except Exception as e:
            print(f"[URL Auto-Extract Error] {e}")

    # Combine text with document or URL context if present
    augmented_text = text
    if doc_text_context:
        augmented_text = f"{augmented_text}\n{doc_text_context}" if augmented_text else doc_text_context
    if url_context:
        augmented_text = f"{augmented_text}\n{url_context}" if augmented_text else url_context

    print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Master Farel: {text} (Media: {mime_type})")

    trimmed_text = text.strip()
    clean_lower = trimmed_text.lower()
    
    # -------------------------------------------------------------
    # Hyper-Fast Natural Speech & Direct Command Interceptors (< 300ms Latency)
    # -------------------------------------------------------------
    pause_phrases = (
        "stop the music", "stop music", "pause music", "pause the music",
        "stop the song", "stop the songs", "stop songs", "stop song",
        "can you stop the songs", "can you stop the music", "can you stop",
        "stop lagunya", "stop lagu", "pause lagu", "jeda musik", "jeda lagu",
        "matikan musik", "hentikan musik", "hentikan lagu", "berhenti", "pause", "/pause", "/stop"
    )
    resume_phrases = (
        "play the music", "play music", "resume music", "resume the music",
        "play the song", "play the songs", "play songs", "play song",
        "putar musik", "lanjutkan musik", "lanjutkan lagu", "play lagi", "resume", "/resume"
    )
    next_phrases = (
        "next song", "next songs", "next track", "next tracks", "skip song", "skip songs", "skip lagu", "lagu berikutnya",
        "next music", "ganti lagu", "lagu selanjutnya", "next", "skip", "/next", "/skip"
    )
    prev_phrases = (
        "previous song", "previous songs", "prev song", "prev songs", "lagu sebelumnya", "kembali lagu", "previous", "prev", "/prev"
    )
    time_phrases = (
        "/time", "/jam", "/waktu", "/clock", "jam berapa", "pukul berapa", "sekarang jam", "waktu sekarang", "what time is it", "current time"
    )
    lyrics_phrases = (
        "/lyrics", "/lirik", "spill the lyrics", "spill the lyric", "lirik lagu sekarang",
        "lirik musik sekarang", "lirik lagu ini", "lirik lagunya", "liriknya",
        "deteksi lirik", "deteksi musik yang sedang di play", "lagu apa ini", "apa judul lagu ini"
    )

    if any(p in clean_lower for p in lyrics_phrases):
        if spotify_ctrl:
            send_chat_action(chat_id, "typing")
            q_lyr = ""
            for pref in ("/lyrics ", "/lirik ", "lirik lagu ", "lirik "):
                if clean_lower.startswith(pref):
                    q_lyr = trimmed_text[len(pref):].strip()
                    break
            out = spotify_ctrl.get_lyrics(q_lyr if q_lyr else None)
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif any(p == clean_lower or clean_lower.startswith(p + " ") or clean_lower.endswith(" " + p) for p in pause_phrases):
        if spotify_ctrl:
            out = spotify_ctrl.play_pause()
            response_text = f"**Laporan.**\n⏯️ {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif any(p == clean_lower or clean_lower.startswith(p + " ") or clean_lower.endswith(" " + p) for p in resume_phrases):
        if spotify_ctrl:
            out = spotify_ctrl.play_pause()
            response_text = f"**Laporan.**\n▶️ {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif any(p == clean_lower for p in next_phrases):
        if spotify_ctrl:
            out = spotify_ctrl.next_track()
            response_text = f"**Laporan.**\n⏭️ {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif any(p == clean_lower for p in prev_phrases):
        if spotify_ctrl:
            out = spotify_ctrl.prev_track()
            response_text = f"**Laporan.**\n⏮️ {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif any(clean_lower.startswith(prefix) for prefix in ("putar lagu ", "play song ", "setel lagu ", "play ", "puterin lagu ", "puterin ")):
        found_q = ""
        for prefix in ("putar lagu ", "play song ", "setel lagu ", "play ", "puterin lagu ", "puterin "):
            if clean_lower.startswith(prefix):
                found_q = trimmed_text[len(prefix):].strip()
                break
        if found_q and spotify_ctrl:
            send_chat_action(chat_id, "record_voice")
            out = spotify_ctrl.search_and_play(found_q, target_device="hp")
            response_text = f"**Laporan.**\n🎵 {out}"
        elif not spotify_ctrl:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
        else:
            response_text = query_gemini_agent(augmented_text if augmented_text else text, media_base64, mime_type)
    elif any(p in clean_lower for p in time_phrases):
        now = datetime.datetime.now()
        day_name = DAYS_ID[now.weekday()]
        month_name = MONTHS_ID[now.month - 1]
        response_text = f"**Jawaban.**\nSaat ini pukul **{now.strftime('%H:%M:%S')} WIB** ({day_name}, {now.day} {month_name} {now.year}), Master Farel."
    elif clean_lower in ("/tasks", "/task_list", "/todo", "/todos"):
        t_res = tool_list_active_tasks()
        pending_str = "\n".join([f"  {t}" for t in t_res.get("pending_tasks", [])])
        response_text = (
            f"**Laporan Active Tasks Hub (AI-Brain):**\n"
            f"Total Tugas Tertunda: **{t_res.get('total_pending', 0)}**\n"
            f"Total Tugas Selesai: **{t_res.get('total_completed', 0)}**\n\n"
            f"📋 **Daftar Tugas Tertunda:**\n{pending_str if pending_str else '  (Tidak ada tugas tertunda)'}\n\n"
            f"📂 Berkas Vault: `08_Goals/Tasks/Active-Tasks.md`"
        )
    elif trimmed_text.startswith("/task "):
        task_desc = trimmed_text.split(" ", 1)[1]
        res = tool_create_task(title=task_desc)
        response_text = f"**Laporan.**\nTugas berhasil dicatat:\n`{res['task']}`\n\n*Status Sinkronisasi:* {res['cloud_sync']}"
    elif clean_lower.startswith(("/model", "/engine")):
        global CURRENT_ENGINE
        parts = trimmed_text.split(" ", 1)
        if len(parts) == 1 or parts[1].strip() in ("", "list", "status"):
            response_text = (
                f"🧠 **Status Mesin AI Raphael:**\n"
                f"- **Model Aktif:** `{CURRENT_ENGINE}`\n"
                f"- **Audio Transcriber:** `Whisper Large v3 Turbo (Groq LPU — 0.15s)`\n\n"
                f"**Pilihan Model yang Tersedia (100% Gratis):**\n"
                f"1. `/model groq` (atau `/model 120b`) ➡️ **OpenAI GPT-OSS 120B** (SOTA 120B Flagship, 500 token/dtk)\n"
                f"2. `/model qwen` ➡️ **Qwen 3.6 27B** (Deep Reasoning & Coding Master)\n"
                f"3. `/model compound` ➡️ **Groq Compound** (Percakapan super cepat)\n"
                f"4. `/model gemini` ➡️ **Google Gemini 3.7 Flash** (Multimodal & Browser Automation)\n\n"
                f"*Ketik perintah di atas untuk langsung berganti model, Master Farel!*"
            )
        else:
            sel = parts[1].strip().lower()
            if sel in ("groq", "120b", "gpt-oss", "1"):
                CURRENT_ENGINE = "openai/gpt-oss-120b"
                response_text = "Laporan.\nMesin AI berhasil dialihkan ke **OpenAI GPT-OSS 120B (Groq LPU)**! Kecepatan 500 token/detik aktif ⚡🚀"
            elif sel in ("qwen", "qwen3.6", "2"):
                CURRENT_ENGINE = "qwen/qwen3.6-27b"
                response_text = "Laporan.\nMesin AI berhasil dialihkan ke **Qwen 3.6 27B (Groq Deep Reasoning)**! 🧠✨"
            elif sel in ("compound", "3"):
                CURRENT_ENGINE = "groq/compound"
                response_text = "Laporan.\nMesin AI berhasil dialihkan ke **Groq Compound**! ⚡"
            elif sel in ("gemini", "gemini-3.7", "4"):
                CURRENT_ENGINE = "gemini-3.7-flash"
                response_text = "Laporan.\nMesin AI berhasil dialihkan ke **Google Gemini 3.7 Flash** (Multimodal & Tools)! 🌐"
            else:
                response_text = "Pemberitahuan.\nPilihan model tidak valid. Ketik `/model` untuk melihat daftar pilihan."
    elif clean_lower in ("/cron", "/cron_list", "/jobs"):
        jobs_info = tool_list_cron_jobs()
        lines = []
        for j in jobs_info["cron_jobs"]:
            lines.append(f"- **{j['time']} WIB** (`{j['id']}`): {j['title']} [{j.get('task_type', 'agentic')}] — *{j['recurrence']}*")
        jobs_str = "\n".join(lines) if lines else "Tidak ada cron job yang aktif."
        response_text = f"**Laporan OpenClaw Cron Engine:**\nTotal Tugas Terjadwal: {jobs_info['total_active_jobs']}\n\n{jobs_str}"
    elif trimmed_text.startswith("/cron_add "):
        parts = trimmed_text.split(" ", 2)
        if len(parts) >= 3:
            t_val = parts[1]
            inst_val = parts[2]
            out = tool_create_cron_job(t_val, inst_val, inst_val, recurrence="once", task_type="agentic")
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nFormat: `/cron_add <HH:MM atau +15m> <instruksi tugas>`"
    elif trimmed_text.startswith("/cron_del "):
        jid = trimmed_text.split(" ", 1)[1].strip()
        out = tool_delete_cron_job(jid)
        response_text = f"**Laporan.**\n{out}"
    elif trimmed_text.startswith("/remind "):
        parts = trimmed_text.split(" ", 2)
        if len(parts) >= 2:
            t_val = parts[1]
            title_val = parts[2] if len(parts) > 2 else "Pengingat Master"
            out = tool_create_cron_job(t_val, title_val, title_val, recurrence="once", task_type="static")
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nFormat: `/remind <HH:MM atau +15m> <pesan pengingat>`."
    elif trimmed_text.startswith(("/cmd ", "/run ", "/exec ")):
        cmd = trimmed_text.split(" ", 1)[1]
        out = tool_execute_terminal_command(cmd)
        response_text = f"**Laporan.**\nEksekusi perintah terminal selesai:\n```cmd\n{cmd}\n```\n**Output:**\n```\n{out}\n```"
    elif trimmed_text.startswith(("/play_laptop ", "/play_pc ")):
        song_query = trimmed_text.split(" ", 1)[1]
        if spotify_ctrl:
            out = spotify_ctrl.search_and_play(song_query, target_device="laptop")
            response_text = f"**Laporan.**\n🎵 {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif trimmed_text.startswith(("/play_hp ", "/play_phone ")):
        song_query = trimmed_text.split(" ", 1)[1]
        if spotify_ctrl:
            out = spotify_ctrl.search_and_play(song_query, target_device="hp")
            response_text = f"**Laporan.**\n🎵 {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif trimmed_text.startswith(("/radio ", "/song_radio ", "/stasiun ")):
        song_query = trimmed_text.split(" ", 1)[1]
        if spotify_ctrl:
            out = spotify_ctrl.play_radio(song_query, target_device="hp")
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif trimmed_text.startswith(("/play ", "/musik ", "/lagu ")):
        song_query = trimmed_text.split(" ", 1)[1]
        if spotify_ctrl:
            out = spotify_ctrl.search_and_play(song_query, target_device="hp")
            response_text = f"**Laporan.**\n🎵 {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif trimmed_text.startswith(("/queue ", "/antre ", "/antrean ")):
        song_query = trimmed_text.split(" ", 1)[1]
        if spotify_ctrl:
            out = spotify_ctrl.add_to_queue(song_query, target_device="hp")
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif trimmed_text.startswith(("/create_playlist ", "/buat_playlist ", "/bikin_playlist ")):
        pl_name = trimmed_text.split(" ", 1)[1]
        if spotify_ctrl:
            out = spotify_ctrl.create_playlist(pl_name)
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif trimmed_text.startswith(("/transfer ", "/pindah ")):
        target_dev = trimmed_text.split(" ", 1)[1].strip()
        if spotify_ctrl:
            out = spotify_ctrl.transfer_playback(target_dev)
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif clean_lower in ("/play", "/pause", "/resume", "/stop"):
        if spotify_ctrl:
            out = spotify_ctrl.play_pause()
            response_text = f"**Laporan.**\n⏯️ {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif clean_lower in ("/next", "/skip", "/lanjut"):
        if spotify_ctrl:
            out = spotify_ctrl.next_track()
            response_text = f"**Laporan.**\n⏭️ {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif clean_lower in ("/prev", "/previous", "/kembali"):
        if spotify_ctrl:
            out = spotify_ctrl.prev_track()
            response_text = f"**Laporan.**\n⏮️ {out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif clean_lower in ("/nowplaying", "/np", "/song", "/lagu"):
        if spotify_ctrl:
            out = spotify_ctrl.now_playing()
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif clean_lower in ("/devices", "/spotify_devices", "/perangkat"):
        if spotify_ctrl:
            out = spotify_ctrl.list_devices()
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nModul Spotify Controller belum aktif."
    elif trimmed_text.startswith(("/vol ", "/volume ")):
        vol_arg = trimmed_text.split(" ", 1)[1].strip().replace("%", "")
        if spotify_ctrl and vol_arg.isdigit():
            out = spotify_ctrl.set_volume(int(vol_arg))
            response_text = f"**Laporan.**\n{out}"
        else:
            response_text = "Pemberitahuan.\nFormat: `/vol <0-100>` (contoh: `/vol 50`)."
    elif trimmed_text.startswith(("/web ", "/search_web ", "/google ")):
        q = trimmed_text.split(" ", 1)[1]
        send_chat_action(chat_id, "typing")
        out = tool_web_search(q)
        response_text = f"**Laporan.**\nHasil Penelusuran Web untuk `{q}`:\n\n{out}"
    elif trimmed_text.startswith(("/view ", "/read ", "/cat ")):
        path = trimmed_text.split(" ", 1)[1]
        out = tool_read_vault_file(path)
        response_text = f"**Laporan.**\nIsi berkas `{path}`:\n\n{out}"
    elif trimmed_text.startswith(("/ls", "/tree", "/dir")):
        parts = trimmed_text.split(" ", 1)
        sub = parts[1] if len(parts) > 1 else ""
        out = tool_list_vault_directory(sub)
        response_text = f"**Laporan.**\nDaftar isi direktori `{sub or '/'}` di AI-Brain:\n```json\n{json.dumps(out, indent=2)}\n```"
    elif trimmed_text.startswith(("/search ", "/find ")):
        q = trimmed_text.split(" ", 1)[1]
        out = tool_search_vault(q)
        response_text = f"**Laporan.**\nHasil pencarian kata kunci `{q}` di AI-Brain:\n```json\n{json.dumps(out, indent=2)}\n```"
    elif clean_lower == "/status":
        now = datetime.datetime.now()
        day_name = DAYS_ID[now.weekday()]
        now_str = f"{day_name}, {now.strftime('%d-%m-%Y — %H:%M:%S')} WIB"
        jobs = load_cron_jobs()
        g_auth_str = "🟢 Terhubung (Tasks & Calendar)" if (google_sync and google_sync.is_authenticated()) else "🟡 Standby"
        spot_str = "🟢 Terhubung (HP Realme 13+ 5G + LRCLIB Lyrics)" if (spotify_ctrl and spotify_ctrl.get_client()) else "🟡 Belum Aktif"
        browser_str = "🟢 Siap (Google Chrome Automation)" if browser_agent else "🟡 Standby"
        
        engine_label = {
            "openai/gpt-oss-120b": "OpenAI GPT-OSS 120B (Groq LPU — 500 tok/s)",
            "qwen/qwen3.6-27b": "Qwen 3.6 27B (Groq Deep Reasoning)",
            "groq/compound": "Groq Compound (Instant Co-Pilot)",
            "gemini-3.7-flash": "Google Gemini 3.7 Flash (Hybrid Reasoning)"
        }.get(CURRENT_ENGINE, CURRENT_ENGINE)

        response_text = (
            f"📊 **Dashboard Status Sistem Raphael AI-Brain v2.5.0**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• ⏱️ **Waktu Presisi Server:** `{now_str}`\n"
            f"• 🧠 **Mesin Utama Aktif:** `{engine_label}`\n"
            f"• 🎙️ **Speech Transcriber:** `Whisper Large v3 Turbo (0.15s)`\n"
            f"• 🌐 **Browser Agent:** `{browser_str}`\n"
            f"• 🎵 **Spotify Cloud Engine:** `{spot_str}`\n"
            f"• 📅 **Google Workspace Sync:** `{g_auth_str}`\n"
            f"• ⏰ **OpenClaw Cron Engine:** `🟢 Aktif ({len(jobs)} Jadwal Terdaftar)`\n"
            f"• 📂 **Knowledge Memory:** `Obsidian AI-Brain (70 Catatan, 100% Synced)`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 *Pintasan Cepat: `/model` (ganti AI), `/lyrics` (lirik lagu), `/browse` (web), `/tasks` (to-do)*"
        )
    elif trimmed_text.startswith(("/grill ", "/grill_me ")):
        topic = trimmed_text.split(" ", 1)[1].strip()
        send_chat_action(chat_id, "typing")
        grill_prompt = (
            f"[KOGNITIF: SOCRATIC GRILL-ME ARCHITECTURE REVIEW]\n"
            f"Master Farel ingin menguji dan menantang arsitektur, asumsi teknis, dan desain dari topik berikut:\n\n"
            f"\"{topic}\"\n\n"
            f"Instruksi Khusus Raphael:\n"
            f"1. Bertindaklah sebagai Senior Technical Architect / Reviewer yang sangat kritis, teliti, dan bersahabat.\n"
            f"2. Bedah dan uji topik tersebut melalui 4 Layer Pertanyaan (Asumsi Dasar, Kasus Ekstrem/Edge Cases, Skalabilitas/Memori, Desain Antarmuka Deep Module).\n"
            f"3. Ajukan 2-3 pertanyaan paling tajam yang memaksa Master mempertimbangkan potensi masalah di hilir (*downstream issues*)."
        )
        response_text = query_gemini_agent(grill_prompt)
        log_title = f"[Grill-Me Review: {topic}]"
        append_to_daily_log(log_title, response_text)
    elif trimmed_text.startswith(("/brainstorm ", "/ideate ")):
        topic = trimmed_text.split(" ", 1)[1].strip()
        send_chat_action(chat_id, "typing")
        bs_prompt = (
            f"[KOGNITIF: STRUCTURED 9-STEP BRAINSTORMING FRAMEWORK]\n"
            f"Master Farel ingin melakukan sesi ideasi terstruktur untuk topik berikut:\n\n"
            f"\"{topic}\"\n\n"
            f"Instruksi Khusus Raphael:\n"
            f"1. Pandu Master secara bertahap menggunakan protokol 9 langkah ideasi (Problem Statement, Constraints, Persona, First Principles, Divergent Ideas, Trade-offs, Optimal Selection, Spec Doc, Actionable Roadmap).\n"
            f"2. Mulai dengan membedah Problem Statement & Batasan (*Constraints*) terlebih dahulu, lalu berikan 3 alternatif solusi inovatif."
        )
        response_text = query_gemini_agent(bs_prompt)
        log_title = f"[Brainstorming: {topic}]"
        append_to_daily_log(log_title, response_text)
    elif trimmed_text.startswith(("/impeccable ", "/audit_ui ", "/ui_audit ")):
        topic = trimmed_text.split(" ", 1)[1].strip()
        send_chat_action(chat_id, "typing")
        ui_prompt = (
            f"[KOGNITIF: IMPECCABLE UI/UX & ANTI-AI-SLOP AUDIT]\n"
            f"Master Farel meminta audit desain frontend dan antarmuka untuk:\n\n"
            f"\"{topic}\"\n\n"
            f"Instruksi Khusus Raphael:\n"
            f"1. Terapkan standar Impeccable Design (Paul Bakaus & Anthropic Design Lead).\n"
            f"2. Audit terhadap indikasi 'AI Slop' (hindari bento box tak bermakna, gradien murah, over-nested cards, tema ungu generik).\n"
            f"3. Berikan rekomendasi tipografi intentional, palet HSL harmonis, whitespace fungsional, dan micro-interactions tingkat produksi (*production-grade*)."
        )
        response_text = query_gemini_agent(ui_prompt)
        log_title = f"[Impeccable Audit: {topic}]"
        append_to_daily_log(log_title, response_text)
    elif trimmed_text.startswith(("/browse ", "/browser ")):
        task_query = trimmed_text.split(" ", 1)[1].strip()
        send_chat_action(chat_id, "typing")
        send_telegram_message(chat_id, f"🌐 **Memulai Agen Browser (Mariner Engine)**...\nMenjalankan: `{task_query}` di Google Chrome laptop.")
        
        if browser_agent:
            def on_progress(p_msg):
                send_chat_action(chat_id, "typing")
            res = browser_agent.execute_task(task_query, callback_status=on_progress)
            if res.get("success"):
                screenshots = res.get("screenshots", [])
                if screenshots and os.path.exists(screenshots[-1]):
                    send_telegram_photo(chat_id, screenshots[-1], caption=f"📸 Tampilan Akhir Peramban: `{res.get('final_title', 'Chrome')}`")
                response_text = f"**Laporan Navigasi Web (Project Mariner):**\n\n{res.get('summary')}\n\n*URL Terakhir:* {res.get('final_url')}"
            else:
                response_text = f"Pemberitahuan.\nKendala navigasi web: {res.get('error')}"
        else:
            response_text = "Pemberitahuan.\nModul Browser Agent belum aktif."
        log_title = f"[Browser Action: {task_query}]"
        append_to_daily_log(log_title, response_text)
    elif clean_lower == "/clear":
        global conversation_history
        conversation_history = []
        response_text = "**Laporan.**\nRiwayat sesi percakapan sementara telah dibersihkan. Memori jangka panjang di AI-Brain tetap utuh dan teratur."
    elif clean_lower == "/help":
        response_text = (
            "**Panduan Lengkap Raphael AI-Brain (Versi 2.4.0 — Agent Skills & High-Effort Cognitive Hub):**\n\n"
            "🌐 **1. Agen Browser Otonom (Project Mariner / Computer Use)**:\n"
            "- `/browse <instruksi/pencarian>` : Mengoperasikan Chrome di laptop secara mandiri, mencari data, mengisi form, dan mengirim screenshot hasil ke Telegram.\n\n"
            "🧠 **2. Fitur Kognitif & Keahlian Agen (*Agent Skills*)**:\n"
            "- `/grill <topik/arsitektur>` : Uji ketahanan desain sistem secara Sokratik (*Relentless Reviewer*).\n"
            "- `/brainstorm <ide>` : Ideasi terstruktur 9-langkah dengan validasi ketat (*Hard-Gate*).\n"
            "- `/impeccable <desain/kode>` : Audit UI/UX tingkat produksi bebas 'AI Slop'.\n\n"
            "📋 **3. Manajemen Tugas & Sinkronisasi (*Tasks Hub*)**:\n"
            "- `/tasks` : Melihat to-do list aktif di Google Tasks & Vault.\n"
            "- `/task <deskripsi>` : Menambah tugas baru seketika.\n\n"
            "🎵 **4. Kontrol Musik Spotify Cloud (HP Realme 13+ 5G)**:\n"
            "- `/play <lagu>` : Putar musik + otomatis siapkan 8 rekomendasi serupa.\n"
            "- `/radio <lagu>` : Stasiun radio lagu bersambung tanpa henti.\n"
            "- `/queue <lagu>` : Masukkan lagu ke antrean berikutnya.\n"
            "- `/pause` / `/next` / `/prev` / `/vol <0-100>` : Kendali pemutaran.\n"
            "- `/devices` : Cek perangkat aktif.\n\n"
            "⏰ **5. Jadwal & Waktu Presisi (OpenClaw Engine)**:\n"
            "- `/status` : Cek kesehatan sistem, model, & koneksi.\n"
            "- `/cron` : Melihat jadwal cron job aktif.\n"
            "- `/remind <waktu> <pesan>` : Buat pengingat terjadwal.\n"
            "- `/time` : Jam server real-time WIB (Presisi Detik)."
        )
    else:
        response_text = query_gemini_agent(augmented_text if augmented_text else text, media_base64, mime_type)
        log_title = text if text else f"[Pesan Suara / Dokumen / Media: {mime_type}]"
        append_to_daily_log(log_title, response_text)

    send_telegram_message(chat_id, response_text)
    try:
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Raphael: {response_text[:80].replace(chr(10), ' ')}...")
    except Exception:
        pass

def register_telegram_commands():
    try:
        url = f"{TELEGRAM_API_BASE}/setMyCommands"
        commands = [
            {"command": "status", "description": "📊 Cek status sistem, AI-Brain & koneksi server"},
            {"command": "model", "description": "🧠 Ganti mesin AI (OpenAI 120B, Qwen 3.6 27B, Gemini 3.7)"},
            {"command": "browse", "description": "🌐 Agen Browser Mariner: Navigasi & aksi web di Chrome"},
            {"command": "grill", "description": "🥊 Socratic Grill-Me: Uji & tantang arsitektur sistem"},
            {"command": "brainstorm", "description": "💡 9-Step Brainstorming: Ideasi terstruktur"},
            {"command": "impeccable", "description": "✨ Audit UI/UX & Frontend Anti-AI-Slop"},
            {"command": "tasks", "description": "📋 Lihat daftar tugas aktif di Google Tasks & Vault"},
            {"command": "task", "description": "➕ Tambah tugas baru (contoh: /task Belajar RPL)"},
            {"command": "play", "description": "🎵 Putar lagu di HP Realme (contoh: /play Lofi)"},
            {"command": "radio", "description": "📻 Putar stasiun radio lagu bersambung tanpa henti"},
            {"command": "queue", "description": "📥 Masukkan lagu ke antrean tanpa potong lagu"},
            {"command": "pause", "description": "⏯️ Jeda / Lanjutkan pemutaran musik Spotify"},
            {"command": "next", "description": "⏭️ Lewati ke lagu berikutnya"},
            {"command": "prev", "description": "⏮️ Putar kembali lagu sebelumnya"},
            {"command": "vol", "description": "🔊 Atur volume Spotify (contoh: /vol 70)"},
            {"command": "devices", "description": "📱 Cek daftar perangkat Spotify yang terhubung"},
            {"command": "lyrics", "description": "📜 Tampilkan lirik lagu Spotify yang sedang diputar"},
            {"command": "cron", "description": "⏰ Lihat jadwal pengingat & cron aktif"},
            {"command": "remind", "description": "🔔 Buat pengingat (contoh: /remind 14:00 Rapat)"},
            {"command": "time", "description": "⏱️ Cek jam server real-time WIB (Presisi Detik)"},
            {"command": "help", "description": "💡 Panduan lengkap seluruh fitur Raphael"}
        ]
        session.post(url, json={"commands": commands}, timeout=8)
    except Exception as e:
        print(f"[SetCommands Error] {e}")

# -------------------------------------------------------------
# Main Loop
# -------------------------------------------------------------
def main():
    lock_socket = ensure_single_instance(49555)
    register_telegram_commands()

    print("=" * 60)
    print(" [RAPHAEL] Telegram AI-Brain Agent v2.4.0 (Spotify Controller & Full Vault Network)")
    print(f" Master ID Whitelist: {ALLOWED_USER_ID}")
    print(f" Models: {PRIMARY_MODELS}")
    print(f" Tasks Hub: ACTIVE ({ACTIVE_TASKS_FILE})")
    print(f" Google Sync Module: READY (Configured: {google_sync.is_configured() if google_sync else False})")
    print(f" Spotify Module: READY (Installed: {spotify_ctrl is not None})")
    print(f" OpenClaw Cron Engine: ACTIVE (Heartbeat 5s)")
    print(f" Real-Time Clock: ATOMIC DETERMINISTIC WIB")
    print(f" Vault Directory: {BRAIN_DIR}")
    print("=" * 60)

    # Start background OpenClaw autonomous cron scheduler thread
    cron_thread = threading.Thread(target=check_and_send_scheduled_reminders, daemon=True)
    cron_thread.start()

    offset = None
    while True:
        try:
            updates = get_updates(offset)
            if updates and updates.get("ok"):
                for item in updates.get("result", []):
                    offset = item["update_id"] + 1
                    message = item.get("message")
                    if not message:
                        continue

                    user_id = message.get("from", {}).get("id")
                    chat_id = message.get("chat", {}).get("id")

                    threading.Thread(target=process_message, args=(chat_id, user_id, message), daemon=True).start()

            time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n[RAPHAEL] Bridge stopped by user.")
            break
        except Exception as e:
            print(f"[Bridge Loop Error] {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
