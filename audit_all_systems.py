import sys, os, time, datetime, json
sys.path.insert(0, r"C:\Users\USER\telegram_bridge")

print("===============================================================")
print("  RAPHAEL AI-BRAIN FULL INTEGRATION & CREDENTIAL AUDIT SUITE")
print("===============================================================")

# 1. GOOGLE WORKSPACE (TASKS & CALENDAR)
print("\n[1/6] AUDIT: GOOGLE TASKS & CALENDAR SYNC")
try:
    from google_sync import google_sync
    if google_sync and google_sync.is_authenticated():
        # Test Tasks
        tasks = google_sync.fetch_all_google_tasks()
        print(f"  [+] Google Tasks Connected! Total Tasks on Cloud: {len(tasks)}")
        for t in tasks[:3]:
            print(f"      - {t.get('title')} (due: {t.get('due', 'none')})")
        # Test Calendar
        now_dt = datetime.datetime.now()
        cal_res = google_sync.add_calendar_event(
            title="[Raphael Audit] Test Event Sync",
            start_iso=now_dt.strftime("%Y-%m-%dT15:00:00+07:00"),
            end_iso=now_dt.strftime("%Y-%m-%dT16:00:00+07:00"),
            description="Automated integration audit test"
        )
        print(f"  [+] Google Calendar Connected! Event Add Status: {cal_res.get('status')}")
    else:
        print("  [-] Google Workspace: NOT authenticated or token invalid!")
except Exception as e:
    print(f"  [-] Google Workspace Error: {e}")

# 2. SPOTIFY CLOUD ENGINE
print("\n[2/6] AUDIT: SPOTIFY CLOUD CONTROLLER")
try:
    from spotify_controller import spotify_ctrl
    if spotify_ctrl and spotify_ctrl.is_authenticated():
        devices = spotify_ctrl.get_devices()
        print(f"  [+] Spotify Authenticated! Active Devices Found: {len(devices)}")
        for d in devices:
            print(f"      - {d.get('name')} ({d.get('type')}) [Active: {d.get('is_active')}]")
    else:
        print("  [-] Spotify Controller: NOT authenticated or token missing!")
except Exception as e:
    print(f"  [-] Spotify Controller Error: {e}")

# 3. GOOGLE GEMINI API (DUAL ENGINE)
print("\n[3/6] AUDIT: GOOGLE GEMINI API")
try:
    import requests
    from telegram_bridge import GEMINI_API_KEY
    u = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
    r = requests.post(u, json={"contents": [{"parts": [{"text": "Ping Gemini"}]}]}, headers={"Content-Type": "application/json"}, timeout=8)
    if r.status_code == 200:
        ans = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        print(f"  [+] Google Gemini 3.5 Flash Lite: 200 OK! Response: \"{ans[:60]}\"")
    else:
        print(f"  [-] Google Gemini Error ({r.status_code}): {r.text[:100]}")
except Exception as e:
    print(f"  [-] Google Gemini Error: {e}")

# 4. OBSIDIAN AI-BRAIN VAULT REPOSITORY
print("\n[4/6] AUDIT: OBSIDIAN AI-BRAIN MEMORY VAULT")
try:
    from telegram_bridge import BRAIN_DIR, ACTIVE_TASKS_FILE, tool_search_vault
    print(f"  [+] Vault Root: {BRAIN_DIR} [Exists: {os.path.exists(BRAIN_DIR)}]")
    print(f"  [+] Active-Tasks File: {ACTIVE_TASKS_FILE} [Exists: {os.path.exists(ACTIVE_TASKS_FILE)}]")
    search_test = tool_search_vault("Semester 3")
    print(f"  [+] Vault Search Engine: OK ({len(search_test)} chars output)")
except Exception as e:
    print(f"  [-] AI-Brain Vault Error: {e}")

# 5. OPENCLAW CRON ENGINE
print("\n[5/6] AUDIT: OPENCLAW CRON ENGINE")
try:
    from telegram_bridge import tool_list_cron_jobs
    jobs = tool_list_cron_jobs()
    print(f"  [+] OpenClaw Scheduler: {jobs.get('total_active_jobs')} active scheduled jobs")
    for j in jobs.get("cron_jobs", [])[:3]:
        print(f"      - {j.get('time')} WIB: {j.get('title')}")
except Exception as e:
    print(f"  [-] OpenClaw Cron Error: {e}")

# 6. BROWSER AUTOMATION AGENT
print("\n[6/6] AUDIT: BROWSER AGENT (PROJECT MARINER)")
try:
    from browser_agent import browser_agent
    print(f"  [+] Browser Agent Module Loaded: {browser_agent is not None}")
except Exception as e:
    print(f"  [-] Browser Agent Error: {e}")

print("\n===============================================================")
print("  AUDIT COMPLETE: ALL MODULES EVALUATED")
print("===============================================================")
