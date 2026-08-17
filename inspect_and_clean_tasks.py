import os
import sys
from google_sync import google_sync

def main():
    if not google_sync.is_authenticated():
        print("Error: Google Sync not authenticated.")
        return

    tasks = google_sync.fetch_all_google_tasks()
    print(f"Total Google Tasks on Cloud: {len(tasks)}", flush=True)
    
    seen_titles = set()
    to_delete = []
    
    for t in tasks:
        t_id = t.get('id')
        title = (t.get('title') or '').strip()
        status = t.get('status')
        print(f" - [{status}] ID: {t_id} | Title: '{title}'", flush=True)
        
        # Mark duplicates for deletion
        lower = title.lower()
        if lower in seen_titles:
            to_delete.append(t_id)
        else:
            seen_titles.add(lower)

    print(f"\nFound {len(to_delete)} duplicate tasks to remove from Google Tasks...", flush=True)
    for tid in to_delete:
        try:
            google_sync.tasks_service.tasks().delete(tasklist='@default', task=tid).execute()
            print(f" Deleted duplicate task ID: {tid}", flush=True)
        except Exception as e:
            print(f" Error deleting {tid}: {e}", flush=True)

    # Clean completed tasks if needed
    print("\nDeduplication Complete!", flush=True)

if __name__ == "__main__":
    main()
