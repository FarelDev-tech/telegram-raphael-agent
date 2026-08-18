import os
import sys
import json
import time
import difflib
import requests
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Force UTF-8 encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CLIENT_ID = "242a24e3007a42bc9ad27c0c46b788e5"
CLIENT_SECRET = "386784a3e36745e2927ccaf8aefc3c5c"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
DEFAULT_SCOPE = "user-read-playback-state user-modify-playback-state user-read-currently-playing app-remote-control playlist-read-private playlist-read-collaborative user-library-read"

CACHE_PATHS = [
    r"C:\Users\USER\telegram_bridge\.spotify_token.json",
    r"C:\Users\USER\.spotify_token.json",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".spotify_token.json")
]

CACHE_PATH = r"C:\Users\USER\telegram_bridge\.spotify_token.json"
for cp in CACHE_PATHS:
    if os.path.exists(cp) and os.path.isfile(cp):
        CACHE_PATH = cp
        break

def score_track_match(query, track):
    """Calculates fuzzy match score between user query (including typos) and Spotify track candidate."""
    q_lower = query.lower().strip()
    t_name = track["name"].lower()
    artists = " ".join([a["name"].lower() for a in track["artists"]])
    full_target = f"{t_name} {artists}"

    # 1. Full string similarity
    full_ratio = difflib.SequenceMatcher(None, q_lower, full_target).ratio()
    # 2. Track name similarity
    name_ratio = difflib.SequenceMatcher(None, q_lower, t_name).ratio()
    
    # 3. Token overlap with phonetic/typo allowance
    q_words = q_lower.split()
    target_words = full_target.split()
    matched_count = 0
    for qw in q_words:
        if any(qw in tw or difflib.SequenceMatcher(None, qw, tw).ratio() >= 0.70 for tw in target_words):
            matched_count += 1
    token_score = matched_count / len(q_words) if q_words else 0

    return (full_ratio * 0.35) + (name_ratio * 0.25) + (token_score * 0.40)

class SpotifyCloudController:
    def __init__(self):
        scope_to_use = DEFAULT_SCOPE
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    t_data = json.load(f)
                if t_data.get("scope"):
                    scope_to_use = t_data["scope"]
            except Exception:
                pass

        self.sp_oauth = SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=scope_to_use,
            cache_path=CACHE_PATH
        )

    def get_client(self):
        try:
            token_info = self.sp_oauth.get_cached_token()
            if not token_info and os.path.exists(CACHE_PATH):
                with open(CACHE_PATH, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                if "refresh_token" in cached_data:
                    token_info = self.sp_oauth.refresh_access_token(cached_data["refresh_token"])

            if token_info:
                if self.sp_oauth.is_token_expired(token_info):
                    token_info = self.sp_oauth.refresh_access_token(token_info["refresh_token"])
                return spotipy.Spotify(auth=token_info["access_token"])
        except Exception as e:
            print(f"[Spotify get_client Error] {e}")
    def is_authenticated(self):
        return self.get_client() is not None

    def get_devices(self):
        sp = self.get_client()
        if not sp:
            return []
        try:
            return sp.devices().get("devices", [])
        except Exception:
            return []

    def get_devices_dict(self, sp):
        devs = sp.devices().get("devices", [])
        phone = None
        laptop = None
        active = None
        for d in devs:
            dtype = d.get("type", "").lower()
            dname = d.get("name", "").lower()
            if d.get("is_active"):
                active = d
            if dtype in ("smartphone", "phone") or any(k in dname for k in ["realme", "android", "iphone", "samsung", "xiaomi", "redmi", "poco", "oppo", "vivo", "infinix"]):
                phone = d
            elif dtype in ("computer", "pc") or "win" in dname:
                laptop = d
        return {"phone": phone, "laptop": laptop, "active": active, "all": devs}

    def search_best_track(self, sp, query):
        clean_query = query.strip()
        res = sp.search(q=clean_query, limit=10, type="track")
        tracks = res.get("tracks", {}).get("items", [])
        if not tracks:
            return None, None
        
        scored = [(score_track_match(clean_query, t), t) for t in tracks]
        scored.sort(key=lambda x: x[0], reverse=True)
        best_track = scored[0][1]
        
        track_name = best_track["name"]
        artists = ", ".join([a["name"] for a in best_track["artists"]])
        album = best_track.get("album", {}).get("name", "")
        typo_notice = f" *(Kecocokan cerdas untuk '{clean_query}')*" if clean_query.lower() not in track_name.lower() else ""
        info_str = f"🎵 **{track_name}** - {artists} (Album: {album}){typo_notice}"
        
        return best_track, info_str

    def seed_recommended_queue(self, sp, seed_track, target_id):
        """Automatically fetches and populates 6-8 relevant recommended tracks into the Spotify queue."""
        try:
            artist_name = seed_track["artists"][0]["name"] if seed_track.get("artists") else ""
            seed_uri = seed_track.get("uri")
            
            queued_uris = set([seed_uri])
            recommended_list = []

            # 1. Fetch tracks by the same artist
            if artist_name:
                res1 = sp.search(q=f"artist:{artist_name}", limit=8, type="track")
                for t in res1.get("tracks", {}).get("items", []):
                    if t["uri"] not in queued_uris:
                        queued_uris.add(t["uri"])
                        recommended_list.append(t)
                    if len(recommended_list) >= 4:
                        break

            # 2. Fetch popular tracks with similar vibe / genre
            if artist_name:
                res2 = sp.search(q=f"{artist_name} pop radio hits", limit=10, type="track")
                for t in res2.get("tracks", {}).get("items", []):
                    if t["uri"] not in queued_uris:
                        queued_uris.add(t["uri"])
                        recommended_list.append(t)
                    if len(recommended_list) >= 8:
                        break

            # 3. Add to Spotify queue
            for t in recommended_list:
                try:
                    sp.add_to_queue(uri=t["uri"], device_id=target_id)
                    time.sleep(0.15)
                except Exception:
                    pass

            print(f"[Recommended Queue Seeded] Successfully queued {len(recommended_list)} similar tracks for '{seed_track['name']}' by {artist_name}")
            return len(recommended_list)
        except Exception as e:
            print(f"[Queue Seed Error] {e}")
            return 0

    def search_and_play(self, query, target_device="hp", auto_seed_radio=True):
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan. Silakan lakukan autentikasi ulang."
        try:
            clean_query = query.strip()
            is_playlist_query = any(w in clean_query.lower() for w in ["playlist", "album", "kompilasi"])
            
            target_uri = None
            title_info = ""
            best_track_obj = None

            if not is_playlist_query:
                best_track_obj, title_info = self.search_best_track(sp, clean_query)
                if best_track_obj:
                    target_uri = best_track_obj["uri"]

            if not target_uri:
                pl_res = sp.search(q=clean_query, limit=5, type="playlist")
                playlists = pl_res.get("playlists", {}).get("items", [])
                if playlists:
                    pl = playlists[0]
                    target_uri = pl["uri"]
                    title_info = f"📑 Playlist: **{pl['name']}**"

            if not target_uri:
                return f"Pencarian untuk '{clean_query}' tidak ditemukan di katalog Spotify."

            dev_info = self.get_devices_dict(sp)

            if target_device in ("hp", "phone", "smartphone"):
                target = dev_info["phone"]
                if not target:
                    return "📱 **HP Belum Terdeteksi:** Buka aplikasi Spotify di HP Realme Master agar terhubung ke Spotify Connect."
                
                target_id = target["id"]
                target_name = target["name"]

                try:
                    sp.transfer_playback(device_id=target_id, force_play=True)
                    time.sleep(0.3)
                except Exception:
                    pass

                try:
                    try:
                        sp.repeat(state="off", device_id=target_id)
                    except Exception:
                        pass

                    if target_uri.startswith("spotify:track:"):
                        sp.start_playback(device_id=target_id, uris=[target_uri])
                        
                        # Automatically seed 6-8 recommended tracks into the queue
                        if auto_seed_radio and best_track_obj:
                            self.seed_recommended_queue(sp, best_track_obj, target_id)
                    else:
                        sp.start_playback(device_id=target_id, context_uri=target_uri)
                    return f"Sedang memutar di 📱 **HP ({target_name})**:\n{title_info}\n*(Rekomendasi Otomatis Aktif: Antrean lagu-lagu serupa bawaan Spotify telah disiapkan)* ✨"
                except Exception as e:
                    return f"📱 **Perhatian:** Spotify di HP ({target_name}) sedang standby di latar belakang. Silakan buka aplikasi Spotify di HP Master dan tekan Play sekali agar sesi aktif, lalu coba kembali!"

            elif target_device in ("laptop", "computer", "pc"):
                target = dev_info["laptop"] or dev_info["active"] or (dev_info["all"][0] if dev_info["all"] else None)
                if not target:
                    return "💻 Laptop tidak terdeteksi di Spotify."
                target_id = target["id"]
                target_name = target["name"]
                if target_uri.startswith("spotify:track:"):
                    sp.start_playback(device_id=target_id, uris=[target_uri])
                    if auto_seed_radio and best_track_obj:
                        self.seed_recommended_queue(sp, best_track_obj, target_id)
                else:
                    sp.start_playback(device_id=target_id, context_uri=target_uri)
                return f"Sedang memutar di 💻 **Laptop ({target_name})**:\n{title_info}"
            else:
                target = dev_info["phone"] or dev_info["active"] or (dev_info["all"][0] if dev_info["all"] else None)
                if not target:
                    return "Tidak ada perangkat Spotify yang terdeteksi."
                target_id = target["id"]
                target_name = target["name"]
                if target_uri.startswith("spotify:track:"):
                    sp.start_playback(device_id=target_id, uris=[target_uri])
                    if auto_seed_radio and best_track_obj:
                        self.seed_recommended_queue(sp, best_track_obj, target_id)
                else:
                    sp.start_playback(device_id=target_id, context_uri=target_uri)
                return f"Sedang memutar di **{target_name}**:\n{title_info}"
        except Exception as e:
            return f"Error memutar Spotify: {e}"

    def play_radio(self, query, target_device="hp"):
        """Plays a song and populates the queue with a full smart radio of similar tracks."""
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            clean_query = query.strip()
            best_track, title_info = self.search_best_track(sp, clean_query)
            if not best_track:
                return f"Lagu '{clean_query}' tidak ditemukan untuk dibuatkan stasiun Radio."

            dev_info = self.get_devices_dict(sp)
            target = dev_info["phone"] if target_device in ("hp", "phone") else (dev_info["laptop"] or dev_info["active"])
            target = target or dev_info["active"] or (dev_info["all"][0] if dev_info["all"] else None)
            
            if not target:
                return "Perangkat Spotify tidak ditemukan. Buka aplikasi Spotify di HP Master."

            target_id = target["id"]
            
            # Start primary track
            sp.start_playback(device_id=target_id, uris=[best_track["uri"]])
            try:
                sp.repeat(state="off", device_id=target_id)
            except Exception:
                pass

            # Seed full recommended tracks
            count = self.seed_recommended_queue(sp, best_track, target_id)
            artist_name = best_track["artists"][0]["name"]

            return (
                f"📻 **Stasiun Radio Dimulai di 📱 {target['name']}!**\n"
                f"{title_info}\n"
                f"*(Sistem telah menyiapkan {count} antrean lagu-lagu hits serupa dari {artist_name} agar musik mengalir tanpa henti)*"
            )
        except Exception as e:
            return f"Error memulai Radio: {e}"

    def add_to_queue(self, query, target_device="hp"):
        """Adds a track to the playback queue without interrupting current music."""
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            clean_query = query.strip()
            best_track, title_info = self.search_best_track(sp, clean_query)
            if not best_track:
                return f"Pencarian lagu '{clean_query}' tidak ditemukan di Spotify untuk dimasukkan antrean."

            dev_info = self.get_devices_dict(sp)
            target = dev_info["phone"] if target_device in ("hp", "phone") else (dev_info["laptop"] or dev_info["active"])
            target = target or dev_info["active"] or (dev_info["all"][0] if dev_info["all"] else None)

            target_id = target["id"] if target else None
            sp.add_to_queue(uri=best_track["uri"], device_id=target_id)
            
            dev_label = f"📱 **HP ({target['name']})**" if target else "perangkat aktif"
            return (
                f"📥 **Berhasil Ditambahkan ke Antrean (*Queue*) di {dev_label}**:\n"
                f"{title_info}\n"
                f"*(Lagu yang sedang berjalan tetap berlanjut, lagu ini akan diputar berikutnya)*"
            )
        except Exception as e:
            return f"Error menambahkan ke antrean: {e}"

    def create_playlist(self, name, description="Dibuat oleh Raphael AI-Brain", tracks=None):
        """Creates a new playlist on Master's Spotify account and populates it with tracks."""
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            user = sp.current_user()
            user_id = user["id"]
            
            pl = sp.user_playlist_create(user=user_id, name=name, public=True, description=description)
            pl_id = pl["id"]
            pl_url = pl["external_urls"].get("spotify", "")

            added_tracks = []
            if tracks:
                track_uris = []
                for q in tracks:
                    t_obj, _ = self.search_best_track(sp, q)
                    if t_obj:
                        track_uris.append(t_obj["uri"])
                        added_tracks.append(f"- {t_obj['name']} ({', '.join([a['name'] for a in t_obj['artists']])})")
                
                if track_uris:
                    sp.playlist_add_items(playlist_id=pl_id, items=track_uris)

            tracks_str = "\n".join(added_tracks) if added_tracks else "(Playlist kosong, siap diisi)"
            return (
                f"🎉 **Playlist Baru Berhasil Dibuat di Spotify!**\n"
                f"- **Nama Playlist:** `{name}`\n"
                f"- **Total Lagu:** {len(added_tracks)}\n"
                f"- **Tautan Playlist:** [Buka di Spotify]({pl_url})\n\n"
                f"**Daftar Lagu:**\n{tracks_str}"
            )
        except Exception as e:
            return f"Error membuat playlist: {e}"

    def play_pause(self):
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            curr = sp.current_playback()
            if curr and curr.get("is_playing"):
                sp.pause_playback()
                return "Musik Spotify telah dijeda (Paused) ⏸️"
            else:
                dev_info = self.get_devices_dict(sp)
                target = dev_info["phone"] or dev_info["active"] or (dev_info["all"][0] if dev_info["all"] else None)
                if target:
                    sp.start_playback(device_id=target["id"])
                    return f"Musik Spotify dilanjutkan (Playing) di **{target['name']}** ▶️"
                else:
                    return "Tidak ada perangkat Spotify yang aktif."
        except Exception as e:
            return f"Error Play/Pause: {e}"

    def transfer_playback(self, target="hp"):
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            dev_info = self.get_devices_dict(sp)
            if target in ("hp", "phone"):
                dest = dev_info["phone"]
                label = "HP"
            else:
                dest = dev_info["laptop"]
                label = "Laptop"

            if not dest:
                return f"Perangkat {label} tidak ditemukan di Spotify Connect. Buka aplikasi Spotify di {label}."
            sp.transfer_playback(device_id=dest["id"], force_play=True)
            return f"Pemutaran musik telah dialihkan ke 📱 **{dest['name']}** 📲"
        except Exception as e:
            return f"Gagal mengalihkan pemutaran: {e}"

    def next_track(self):
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            sp.next_track()
            time.sleep(0.5)
            return self.now_playing()
        except Exception as e:
            return f"Error beralih ke lagu berikutnya: {e}"

    def prev_track(self):
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            sp.previous_track()
            time.sleep(0.5)
            return self.now_playing()
        except Exception as e:
            return f"Error kembali ke lagu sebelumnya: {e}"

    def now_playing(self):
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            curr = sp.current_playback()
            if not curr or not curr.get("item"):
                return "Tidak ada musik yang sedang diputar saat ini di Spotify."
            
            item = curr["item"]
            track_name = item.get("name", "Unknown")
            artists = ", ".join([a["name"] for a in item.get("artists", [])])
            album = item.get("album", {}).get("name", "")
            progress_ms = curr.get("progress_ms", 0)
            duration_ms = item.get("duration_ms", 1)
            
            prog_min = progress_ms // 60000
            prog_sec = (progress_ms % 60000) // 1000
            dur_min = duration_ms // 60000
            dur_sec = (duration_ms % 60000) // 1000
            
            status = "▶️ Sedang Diputar" if curr.get("is_playing") else "⏸️ Dijeda"
            dev_name = curr.get("device", {}).get("name", "Perangkat")
            dev_type = curr.get("device", {}).get("type", "")

            return (
                f"🎶 **Sedang Diputar di Spotify** ([{dev_type}] {dev_name}):\n"
                f"- **Lagu:** {track_name}\n"
                f"- **Artis:** {artists}\n"
                f"- **Album:** {album}\n"
                f"- **Waktu:** `{prog_min:02d}:{prog_sec:02d} / {dur_min:02d}:{dur_sec:02d}`\n"
                f"- **Status:** {status}"
            )
        except Exception as e:
            return f"Error mengecek info lagu: {e}"

    def list_devices(self):
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            devs = sp.devices().get("devices", [])
            if not devs:
                return "Tidak ada perangkat Spotify yang aktif saat ini. Buka aplikasi Spotify di HP atau laptop Master."
            lines = ["📱 **Daftar Perangkat Spotify Terhubung:**"]
            for d in devs:
                act = "*(Aktif)* ✅" if d.get("is_active") else "*(Standby)*"
                lines.append(f"- `[{d.get('type')}]` **{d.get('name')}** {act} (Vol: {d.get('volume_percent')}%)")
            return "\n".join(lines)
        except Exception as e:
            return f"Error mengambil daftar perangkat: {e}"

    def set_volume(self, percent):
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        try:
            percent = max(0, min(100, int(percent)))
            sp.volume(percent)
            return f"Volume Spotify diatur ke {percent}% 🔊"
        except Exception as e:
            return f"Error mengatur volume: {e}"

    def get_lyrics(self, query=None):
        """Fetches full lyrics for the currently playing Spotify song or a specified song query."""
        sp = self.get_client()
        if not sp:
            return "Error: Token Spotify tidak ditemukan."
        
        track_name = ""
        artist_name = ""
        album_name = ""
        duration_sec = 0

        try:
            if not query or not query.strip():
                # Detect currently playing or recent track across all devices
                sp.requests_timeout = 5
                item = None
                try:
                    curr = sp.currently_playing() or sp.current_playback()
                    if curr and curr.get("item"):
                        item = curr["item"]
                except Exception:
                    pass

                if not item:
                    try:
                        recent = sp.current_user_recently_played(limit=1)
                        if recent and recent.get("items"):
                            item = recent["items"][0]["track"]
                    except Exception:
                        pass

                if not item:
                    return "Tidak ada lagu yang sedang diputar di Spotify saat ini. Putar lagu terlebih dahulu, Master!"
                
                track_name = item.get("name", "")
                artists_list = [a["name"] for a in item.get("artists", [])]
                artist_name = artists_list[0] if artists_list else ""
                album_name = item.get("album", {}).get("name", "")
                duration_sec = item.get("duration_ms", 0) // 1000
            else:
                # Query specified by user
                clean_q = query.strip()
                t_obj, _ = self.search_best_track(sp, clean_q)
                if t_obj:
                    track_name = t_obj.get("name", clean_q)
                    artists_list = [a["name"] for a in t_obj.get("artists", [])]
                    artist_name = artists_list[0] if artists_list else ""
                    album_name = t_obj.get("album", {}).get("name", "")
                else:
                    track_name = clean_q

            if not track_name:
                return "Judul lagu tidak dapat diidentifikasi."

            # Query lrclib API
            url = "https://lrclib.net/api/get"
            params = {
                "track_name": track_name,
                "artist_name": artist_name
            }
            if duration_sec > 0:
                params["duration"] = duration_sec

            headers = {"User-Agent": "Raphael-AI-Brain/2.4.0"}
            lyrics_body = ""
            try:
                res = requests.get(url, params=params, headers=headers, timeout=8)
                if res.status_code == 200:
                    data = res.json()
                    lyrics_body = data.get("plainLyrics") or data.get("syncedLyrics")
            except Exception as e:
                print(f"[LRCLIB Error] {e}")

            # Fallback to general search if lrclib has no match
            if not lyrics_body:
                try:
                    from ddgs import DDGS
                    ddgs = DDGS()
                    s_results = list(ddgs.text(f"{track_name} {artist_name} lyrics", max_results=3))
                    if s_results:
                        lyrics_body = "\n\n".join([r.get("body", "") for r in s_results if r.get("body")])
                except Exception:
                    pass

            if not lyrics_body:
                return f"Lirik untuk lagu **{track_name}** - *{artist_name}* belum tersedia di basis data lirik publik."

            artist_display = f" - {artist_name}" if artist_name else ""
            album_display = f" (Album: *{album_name}*)" if album_name else ""
            return (
                f"📜 **Lirik Lagu: {track_name}{artist_display}**{album_display}\n\n"
                f"{lyrics_body}"
            )
        except Exception as e:
            return f"Error mengambil lirik: {e}"

spotify_ctrl = SpotifyCloudController()

