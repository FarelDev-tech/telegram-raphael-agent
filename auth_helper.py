import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

CREDENTIALS_FILE = r"C:\Users\USER\telegram_bridge\credentials.json"
TOKEN_FILE = r"C:\Users\USER\telegram_bridge\token.json"
SCOPES = [
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/calendar'
]

def main():
    print("=" * 60)
    print(" [RAPHAEL] Menjalankan Local OAuth Server & Membuka Browser...")
    print("=" * 60)
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    # run_local_server automatically constructs the perfect redirect_uri and opens the browser
    creds = flow.run_local_server(port=0, open_browser=True, prompt='consent', success_message="Autentikasi Berhasil! Anda dapat menutup tab browser ini.")
    with open(TOKEN_FILE, 'w', encoding='utf-8') as token:
        token.write(creds.to_json())
    print(f"\n[SUKSES] Token berhasil dibuat di: {TOKEN_FILE}")

if __name__ == "__main__":
    main()
