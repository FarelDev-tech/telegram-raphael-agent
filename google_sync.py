import os
import sys
import json
import re
import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE") or os.path.join(SCRIPT_DIR, "credentials.json")
TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE") or os.path.join(SCRIPT_DIR, "token.json")
SCOPES = [
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/calendar'
]

class GoogleSyncEngine:
    def __init__(self):
        self.creds = None
        self.tasks_service = None
        self.calendar_service = None
        self._init_service()

    def _init_service(self):
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build

            if os.path.exists(TOKEN_FILE):
                self.creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

            if not self.creds or not self.creds.valid:
                if self.creds and self.creds.expired and self.creds.refresh_token:
                    try:
                        self.creds.refresh(Request())
                        with open(TOKEN_FILE, 'w', encoding='utf-8') as token:
                            token.write(self.creds.to_json())
                    except Exception:
                        self.creds = None

            if self.creds and self.creds.valid:
                self.tasks_service = build('tasks', 'v1', credentials=self.creds)
                self.calendar_service = build('calendar', 'v3', credentials=self.creds)
        except Exception:
            pass

    def is_configured(self):
        return os.path.exists(CREDENTIALS_FILE)

    def is_authenticated(self):
        return self.creds is not None and self.creds.valid

    def fetch_all_google_tasks(self):
        if not self.is_authenticated():
            return []
        try:
            res = self.tasks_service.tasks().list(tasklist='@default', showCompleted=True, showHidden=True).execute()
            return res.get("items", [])
        except Exception as e:
            print(f"[Fetch Google Tasks Error] {e}")
            return []

    def add_task(self, title, notes="", due_date=None):
        if not self.is_authenticated():
            return {"status": "vault_only", "message": "Google Tasks belum diautentikasi."}
        try:
            # Check if task with identical title already exists to avoid duplication
            existing_tasks = self.fetch_all_google_tasks()
            for t in existing_tasks:
                if t.get("status") == "needsAction" and (t.get("title") or "").strip().lower() == title.strip().lower():
                    return {"status": "already_exists", "id": t.get("id"), "title": t.get("title")}

            body = {"title": title, "notes": notes}
            if due_date:
                if len(due_date) == 10:
                    due_date += "T23:59:59Z"
                body["due"] = due_date

            result = self.tasks_service.tasks().insert(tasklist='@default', body=body).execute()
            return {"status": "success", "id": result.get("id"), "title": result.get("title"), "link": result.get("selfLink")}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def delete_task_by_keyword(self, keyword):
        if not self.is_authenticated():
            return {"status": "not_authenticated"}
        deleted_count = 0
        try:
            tasks = self.fetch_all_google_tasks()
            for t in tasks:
                t_title = (t.get("title") or "").strip()
                t_id = t.get("id")
                if keyword.lower() in t_title.lower() or keyword == t_id:
                    self.tasks_service.tasks().delete(tasklist='@default', task=t_id).execute()
                    deleted_count += 1
            return {"status": "success", "deleted_count": deleted_count}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def update_task_by_keyword(self, old_keyword, new_title, new_due_date=None, new_notes=None):
        if not self.is_authenticated():
            return {"status": "not_authenticated"}
        try:
            tasks = self.fetch_all_google_tasks()
            for t in tasks:
                t_title = (t.get("title") or "").strip()
                t_id = t.get("id")
                if old_keyword.lower() in t_title.lower() and t.get("status") == "needsAction":
                    patch_body = {"title": new_title}
                    if new_due_date:
                        if len(new_due_date) == 10:
                            new_due_date += "T23:59:59Z"
                        patch_body["due"] = new_due_date
                    if new_notes is not None:
                        patch_body["notes"] = new_notes

                    res = self.tasks_service.tasks().patch(tasklist='@default', task=t_id, body=patch_body).execute()
                    return {"status": "success", "updated_id": t_id, "new_title": res.get("title")}

            # If not found to patch, create cleanly
            return self.add_task(new_title, new_notes or "", new_due_date)
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def deduplicate_tasks(self, vault_tasks_file=None):
        """Cleans up all duplicates on Google Tasks cloud and Obsidian Active-Tasks.md."""
        if not self.is_authenticated():
            return {"status": "not_authenticated"}
        
        # 1. Clean Google Tasks Cloud
        tasks = self.fetch_all_google_tasks()
        seen = set()
        deleted_cloud = 0
        for t in tasks:
            t_id = t.get("id")
            title = (t.get("title") or "").strip().lower()
            status = t.get("status")
            if not title:
                continue
            key = f"{title}_{status}"
            if key in seen:
                try:
                    self.tasks_service.tasks().delete(tasklist='@default', task=t_id).execute()
                    deleted_cloud += 1
                except Exception:
                    pass
            else:
                seen.add(key)

        # 2. Clean Obsidian Vault file
        cleaned_vault = 0
        if vault_tasks_file and os.path.exists(vault_tasks_file):
            try:
                with open(vault_tasks_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                new_lines = []
                seen_vault_tasks = set()
                for line in lines:
                    s_line = line.strip()
                    if s_line.startswith("- [ ]") or s_line.startswith("- [x]"):
                        # Extract task core text (ignore dates/tags)
                        task_core = s_line.split("📅")[0].split("#")[0].strip().lower()
                        if task_core in seen_vault_tasks:
                            cleaned_vault += 1
                            continue # Skip duplicate!
                        seen_vault_tasks.add(task_core)
                    new_lines.append(line)

                with open(vault_tasks_file, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
            except Exception as e:
                print(f"[Vault Deduplication Error] {e}")

        return {
            "status": "success",
            "deleted_cloud_duplicates": deleted_cloud,
            "deleted_vault_duplicates": cleaned_vault
        }

    def sync_tasks_with_vault(self, vault_tasks_file):
        """Two-way synchronization between Google Tasks cloud and Obsidian Active-Tasks.md."""
        if not self.is_authenticated() or not os.path.exists(vault_tasks_file):
            return {"status": "skipped", "message": "Google auth or vault file not available"}

        # Run deduplication first
        self.deduplicate_tasks(vault_tasks_file)

        google_tasks = self.fetch_all_google_tasks()
        if not google_tasks:
            return {"status": "no_tasks", "synced_count": 0}

        try:
            with open(vault_tasks_file, "r", encoding="utf-8") as f:
                content = f.read()

            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            
            # Map google tasks by normalized title
            gt_map = {}
            for gt in google_tasks:
                t_title = (gt.get("title") or "").strip().lower()
                if t_title:
                    gt_map[t_title] = gt

            lines = content.split("\n")
            new_lines = []
            modified = False

            for line in lines:
                s_line = line.strip()
                if s_line.startswith("- [ ]") or s_line.startswith("- [x]"):
                    # Extract task title
                    # e.g. "- [ ] Bersih-bersih pagi 📅 2026-08-18 #general ✅ 2026-08-18"
                    raw_task = re.sub(r"^-\s*\[[ xX]\]\s*", "", s_line)
                    # Strip existing completed date
                    raw_task_clean = re.sub(r"\s*✅\s*\d{4}-\d{2}-\d{2}.*$", "", raw_task).strip()
                    # Strip due date and tag for matching
                    core_title = re.sub(r"📅\s*\d{4}-\d{2}-\d{2}", "", raw_task_clean)
                    core_title = re.sub(r"#[a-zA-Z0-9_-]+", "", core_title).strip().lower()

                    matched_gt = gt_map.get(core_title)
                    if not matched_gt:
                        # Try partial matching
                        for g_title, g_obj in gt_map.items():
                            if g_title in core_title or core_title in g_title:
                                matched_gt = g_obj
                                break

                    if matched_gt:
                        g_status = matched_gt.get("status", "needsAction")
                        if g_status == "completed":
                            new_line = f"- [x] {raw_task_clean} ✅ {today_str}"
                            if new_line != s_line:
                                modified = True
                            new_lines.append(new_line)
                        else:
                            new_line = f"- [ ] {raw_task_clean}"
                            if new_line != s_line:
                                modified = True
                            new_lines.append(new_line)
                    else:
                        new_lines.append(s_line)
                else:
                    new_lines.append(line)

            # Clean consecutive empty lines
            cleaned_content = []
            for l in new_lines:
                if l.strip() == "" and cleaned_content and cleaned_content[-1].strip() == "":
                    continue
                cleaned_content.append(l)

            final_text = "\n".join(cleaned_content).strip() + "\n"
            with open(vault_tasks_file, "w", encoding="utf-8") as f:
                f.write(final_text)

            return {"status": "success", "modified": modified, "synced_tasks": len(google_tasks)}
        except Exception as e:
            print(f"[Sync Error] {e}")
            return {"status": "error", "message": str(e)}

    def add_calendar_event(self, summary=None, start_iso=None, end_iso=None, description="", location="", title=None):
        if not self.is_authenticated():
            return {"status": "vault_only", "message": "Google Calendar belum diautentikasi."}
        try:
            event_title = summary or title or "Acara Kalender"
            if not end_iso and start_iso:
                st = datetime.datetime.fromisoformat(start_iso)
                end_iso = (st + datetime.timedelta(hours=1)).isoformat()

            event = {
                'summary': event_title,
                'location': location,
                'description': description,
                'start': {
                    'dateTime': start_iso,
                    'timeZone': 'Asia/Jakarta',
                },
                'end': {
                    'dateTime': end_iso,
                    'timeZone': 'Asia/Jakarta',
                },
            }
            res = self.calendar_service.events().insert(calendarId='primary', body=event).execute()
            return {"status": "success", "id": res.get("id"), "summary": res.get("summary"), "htmlLink": res.get("htmlLink")}
        except Exception as e:
            return {"status": "error", "message": str(e)}

# Singleton instance
google_sync = GoogleSyncEngine()
