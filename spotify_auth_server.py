import os
import sys
import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse
import spotipy
from spotipy.oauth2 import SpotifyOAuth

CLIENT_ID = "242a24e3007a42bc9ad27c0c46b788e5"
CLIENT_SECRET = "386784a3e36745e2927ccaf8aefc3c5c"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-playback-state user-modify-playback-state user-read-currently-playing app-remote-control playlist-read-private playlist-read-collaborative user-library-read"
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".spotify_token.json")

sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE,
    cache_path=CACHE_PATH
)

auth_code_received = None

class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code_received
        parsed_url = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed_url.query)
        
        if "code" in params:
            code = params["code"][0]
            auth_code_received = code
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
            <html>
            <head><title>Spotify Berhasil Terhubung</title></head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px; background: #121212; color: #fff;">
                <h1 style="color: #1DB954;">🎉 Autentikasi Spotify Berhasil!</h1>
                <p>Spotify telah berhasil terhubung dengan <b>Raphael AI-Brain</b>.</p>
                <p>Anda dapat menutup tab browser ini dan kembali ke Telegram.</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Error: Code parameter not found.")

def start_server_and_auth():
    print(f"Membuka listener di port 8888...")
    server = HTTPServer(("127.0.0.1", 8888), OAuthHandler)
    server.timeout = 180
    print("Menunggu persetujuan...")
    while not auth_code_received:
        server.handle_request()
    
    if auth_code_received:
        print(f"Menerima Authorization Code! Menukar dengan Token...")
        token_info = sp_oauth.get_access_token(auth_code_received, as_dict=True)
        print(">>> TOKEN BERHASIL DISIMPAN! <<<")
        sp = spotipy.Spotify(auth=token_info['access_token'])
        user = sp.current_user()
        print(f"Akun Terhubung: {user.get('display_name')}")
        return True
    return False

if __name__ == "__main__":
    start_server_and_auth()
