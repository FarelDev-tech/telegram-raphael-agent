import os
import sys
import json
import spotipy
from spotipy.oauth2 import SpotifyOAuth

CLIENT_ID = "242a24e3007a42bc9ad27c0c46b788e5"
CLIENT_SECRET = "386784a3e36745e2927ccaf8aefc3c5c"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
# Fallback redirect URI if user set localhost:8888/callback
SCOPE = "user-read-playback-state user-modify-playback-state user-read-currently-playing app-remote-control playlist-read-private playlist-read-collaborative user-library-read"

CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".spotify_token.json")

def perform_auth():
    print("=" * 60)
    print(" [SPOTIFY AUTH] Memulai Autentikasi Spotify Web API...")
    print(f" Client ID: {CLIENT_ID[:8]}...")
    print(f" Redirect URI: {REDIRECT_URI}")
    print(f" Scopes: {SCOPE}")
    print("=" * 60)

    try:
        sp_oauth = SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=SCOPE,
            cache_path=CACHE_PATH,
            open_browser=True
        )

        token_info = sp_oauth.get_cached_token()
        if not token_info:
            auth_url = sp_oauth.get_authorize_url()
            print(f"\nJika browser tidak terbuka otomatis, buka tautan ini:\n{auth_url}\n")
            print("Menunggu persetujuan di browser...")
            # This opens the browser and starts a local server on port 8888
            token_info = sp_oauth.get_access_token(as_dict=True)

        if token_info:
            print("\n>>> AUTENTIKASI SPOTIFY BERHASIL! <<<")
            sp = spotipy.Spotify(auth=token_info['access_token'])
            user = sp.current_user()
            print(f"Akun Terhubung: {user.get('display_name')} ({user.get('id')})")
            devices = sp.devices()
            print(f"Perangkat Terdeteksi: {len(devices.get('devices', []))} perangkat")
            for d in devices.get('devices', []):
                print(f" - [{d.get('type')}] {d.get('name')} (Active: {d.get('is_active')}) (ID: {d.get('id')})")
            return True
    except Exception as e:
        print(f"\n[AUTH ERROR] {e}")
        return False

if __name__ == "__main__":
    perform_auth()
