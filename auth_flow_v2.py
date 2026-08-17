import os
import sys
import wsgiref.simple_server
import wsgiref.util
from google_auth_oauthlib.flow import InstalledAppFlow, _WSGIRequestHandler, _RedirectWSGIApp

CREDENTIALS_FILE = r"C:\Users\USER\telegram_bridge\credentials.json"
TOKEN_FILE = r"C:\Users\USER\telegram_bridge\token.json"
URL_FILE = r"C:\Users\USER\telegram_bridge\auth_url.txt"
SCOPES = [
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/calendar'
]

def main():
    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    
    # Pick port 8090 (or find free port)
    port = 8090
    host = 'localhost'
    
    wsgi_app = _RedirectWSGIApp("Autentikasi Berhasil! Silakan tutup tab ini dan kembali ke chat.")
    
    # Try binding
    try:
        server = wsgiref.simple_server.make_server(host, port, wsgi_app, handler_class=_WSGIRequestHandler)
    except OSError:
        port = 8095
        server = wsgiref.simple_server.make_server(host, port, wsgi_app, handler_class=_WSGIRequestHandler)
        
    flow.redirect_uri = f"http://{host}:{port}/"
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    
    with open(URL_FILE, "w", encoding="utf-8") as f:
        f.write(auth_url)
        
    print(f"AUTH_READY_URL:\n{auth_url}\n", flush=True)
    
    # Handle the request
    server.handle_request()
    
    authorization_response = wsgi_app.last_request_uri.replace("http:", "https:")
    flow.fetch_token(authorization_response=authorization_response)
    
    with open(TOKEN_FILE, 'w', encoding='utf-8') as token:
        token.write(flow.credentials.to_json())
        
    print(f"\n[SUKSES] Token berhasil disimpan di: {TOKEN_FILE}", flush=True)

if __name__ == "__main__":
    main()
