import os
import spotipy
from spotify_controller import spotify_ctrl

sp = spotify_ctrl.get_client()
if sp:
    query = "Shawn Mendes Mercy"
    res = sp.search(q=query, limit=1, type="track")
    track = res["tracks"]["items"][0]
    track_name = track["name"]
    artist_name = track["artists"][0]["name"]
    artist_id = track["artists"][0]["id"]
    
    print(f"Track: {track_name} by {artist_name}")
    
    # 1. Official Spotify Song Radio Playlist
    radio_res = sp.search(q=f"{track_name} {artist_name} Radio", limit=1, type="playlist")
    playlists = radio_res.get("playlists", {}).get("items", [])
    if playlists:
        print(f"Found Song Radio: '{playlists[0]['name']}' (URI: {playlists[0]['uri']})")
    
    # 2. Artist top tracks & similar tracks
    artist_tracks = sp.artist_top_tracks(artist_id).get("tracks", [])
    print(f"Found {len(artist_tracks)} top tracks by {artist_name}:")
    for t in artist_tracks[:3]:
        print(f" - {t['name']}")
