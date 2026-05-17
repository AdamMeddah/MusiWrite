from __future__ import annotations

import base64
import os
import secrets
import urllib.parse
from datetime import datetime
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, redirect, render_template_string, request, session, url_for
from markupsafe import Markup

from musiwrite.core import (
    SceneAnalysis,
    aggregate_tracks,
    build_search_queries,
    fallback_analysis,
    parse_scene_analysis,
)


load_dotenv()


SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
SPOTIFY_SCOPE = "user-read-private user-read-email playlist-modify-private"


class Config:
    spotify_client_id = os.getenv("SPOTIFY_CLIENT_ID") or os.getenv("CLIENT_ID", "")
    spotify_client_secret = os.getenv("SPOTIFY_CLIENT_SECRET") or os.getenv("CLIENT_SECRET", "")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:5000/callback")
    flask_secret_key = os.getenv("FLASK_SECRET_KEY", secrets.token_hex(32))
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral:7b-instruct-q4_0")
    playlist_size = int(os.getenv("PLAYLIST_SIZE", "40"))


app = Flask(__name__)
app.secret_key = Config.flask_secret_key


PAGE = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>MusiWrite</title>
    <style>
      :root {
        color-scheme: light dark;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        line-height: 1.5;
      }

      body {
        margin: 0;
        min-height: 100vh;
        background: #101418;
        color: #f7fafc;
      }

      main {
        width: min(880px, calc(100% - 32px));
        margin: 0 auto;
        padding: 56px 0;
      }

      h1 {
        margin: 0 0 12px;
        font-size: clamp(2.25rem, 6vw, 4.75rem);
        line-height: 0.95;
      }

      p {
        color: #c9d3df;
        font-size: 1.05rem;
      }

      form {
        display: grid;
        gap: 16px;
        margin-top: 28px;
      }

      label {
        color: #f7fafc;
        font-weight: 700;
      }

      textarea,
      input {
        width: 100%;
        box-sizing: border-box;
        border: 1px solid #354151;
        border-radius: 8px;
        background: #171d23;
        color: #f7fafc;
        padding: 14px;
        font: inherit;
      }

      textarea {
        min-height: 180px;
        resize: vertical;
      }

      button,
      .button {
        width: fit-content;
        border: 0;
        border-radius: 8px;
        background: #45d483;
        color: #06110b;
        cursor: pointer;
        display: inline-flex;
        font: inherit;
        font-weight: 800;
        margin-top: 8px;
        padding: 12px 18px;
        text-decoration: none;
      }

      .result {
        border-left: 4px solid #45d483;
        margin-top: 28px;
        padding-left: 18px;
      }

      .error {
        border-left-color: #ff6b6b;
      }

      code {
        background: #202832;
        border-radius: 6px;
        padding: 2px 6px;
      }
    </style>
  </head>
  <body>
    <main>
      <h1>MusiWrite</h1>
      <p>Turn free-form scene writing into a private Spotify playlist using local Ollama inference.</p>
      {% if not authenticated %}
        <a class="button" href="{{ url_for('login') }}">Connect Spotify</a>
      {% else %}
        <form action="{{ url_for('create_playlist') }}" method="post">
          <div>
            <label for="story_text">Scene text</label>
            <textarea id="story_text" name="story_text" required placeholder="A rain-soaked rooftop chase, neon signs flickering while the hero realizes they have been betrayed."></textarea>
          </div>
          <div>
            <label for="genre">Genre filter</label>
            <input id="genre" name="genre" placeholder="Optional, e.g. synthwave, indie rock, jazz">
          </div>
          <button type="submit">Generate playlist</button>
        </form>
      {% endif %}

      {% if message %}
        <section class="result">{{ message|safe }}</section>
      {% endif %}
      {% if error %}
        <section class="result error">{{ error }}</section>
      {% endif %}
    </main>
  </body>
</html>
"""


def spotify_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def require_spotify_config() -> None:
    missing = []
    if not Config.spotify_client_id:
        missing.append("SPOTIFY_CLIENT_ID")
    if not Config.spotify_client_secret:
        missing.append("SPOTIFY_CLIENT_SECRET")
    if missing:
        raise RuntimeError(f"Missing Spotify setting(s): {', '.join(missing)}")


def authenticated() -> bool:
    expires_at = session.get("expires_at", 0)
    return bool(session.get("access_token") and datetime.now().timestamp() < expires_at)


def token_request(data: dict[str, str]) -> dict[str, Any]:
    auth_string = f"{Config.spotify_client_id}:{Config.spotify_client_secret}"
    auth_bytes = auth_string.encode("utf-8")
    auth_header = base64.b64encode(auth_bytes).decode("utf-8")
    response = requests.post(
        SPOTIFY_TOKEN_URL,
        data=data,
        headers={
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def save_token(token_info: dict[str, Any]) -> None:
    session["access_token"] = token_info["access_token"]
    session["expires_at"] = datetime.now().timestamp() + token_info.get("expires_in", 3600)
    if "refresh_token" in token_info:
        session["refresh_token"] = token_info["refresh_token"]


def refresh_access_token() -> None:
    refresh_token = session.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Spotify session expired. Please connect Spotify again.")
    token_info = token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
    save_token(token_info)


def get_access_token() -> str:
    if not session.get("access_token"):
        raise RuntimeError("Spotify is not connected.")
    if datetime.now().timestamp() >= session.get("expires_at", 0):
        refresh_access_token()
    return session["access_token"]


def call_ollama(story_text: str, genre: str) -> SceneAnalysis:
    prompt = f"""
You extract music direction from creative writing.
Return only compact JSON with these keys:
mood: one lowercase adjective
scene: two to five lowercase words describing the scene
energy: number from 0.0 to 1.0
valence: number from 0.0 to 1.0
genres: array of zero to three genre strings, prioritizing the user genre when present
playlist_title: short title, maximum 48 characters
search_terms: array of four short Spotify playlist search phrases

User genre: {genre or "none"}
Scene text:
{story_text}
"""
    try:
        response = requests.post(
            Config.ollama_url,
            json={"model": Config.ollama_model, "prompt": prompt, "stream": False},
            timeout=45,
        )
        response.raise_for_status()
        generated = response.json().get("response", "")
        return parse_scene_analysis(generated, default_genre=genre)
    except requests.RequestException:
        return fallback_analysis(story_text, genre)


def spotify_get(path: str, access_token: str, **params: Any) -> dict[str, Any]:
    response = requests.get(
        f"{SPOTIFY_API_BASE}{path}",
        headers=spotify_headers(access_token),
        params=params,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def spotify_post(path: str, access_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{SPOTIFY_API_BASE}{path}",
        headers={**spotify_headers(access_token), "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    if response.content:
        return response.json()
    return {}


def get_user_id(access_token: str) -> str:
    return spotify_get("/me", access_token)["id"]


def search_playlists(access_token: str, query: str, limit: int = 4) -> list[dict[str, Any]]:
    payload = spotify_get("/search", access_token, q=query, type="playlist", limit=limit, market="US")
    return [playlist for playlist in payload.get("playlists", {}).get("items", []) if playlist]


def playlist_tracks(access_token: str, playlist_id: str, source_name: str, limit: int = 50) -> list[dict[str, Any]]:
    payload = spotify_get(f"/playlists/{playlist_id}/tracks", access_token, limit=limit, market="US")
    tracks = []
    for item in payload.get("items", []):
        track = item.get("track") or {}
        if track.get("id") and not track.get("is_local"):
            tracks.append(
                {
                    "id": track["id"],
                    "uri": track["uri"],
                    "name": track.get("name", "Untitled"),
                    "artists": [artist["name"] for artist in track.get("artists", [])],
                    "source": source_name,
                }
            )
    return tracks


def source_playlists(access_token: str, analysis: SceneAnalysis) -> list[dict[str, Any]]:
    sources = []
    seen_playlists = set()
    for query in build_search_queries(analysis):
        for playlist in search_playlists(access_token, query):
            playlist_id = playlist["id"]
            if playlist_id in seen_playlists:
                continue
            seen_playlists.add(playlist_id)
            sources.append(
                {
                    "id": playlist_id,
                    "name": playlist.get("name", query),
                    "query": query,
                    "tracks": playlist_tracks(access_token, playlist_id, playlist.get("name", query)),
                }
            )
    return sources


def create_spotify_playlist(access_token: str, user_id: str, title: str, description: str) -> str:
    payload = spotify_post(
        f"/users/{user_id}/playlists",
        access_token,
        {"name": title, "description": description, "public": False},
    )
    return payload["id"]


def add_tracks(access_token: str, playlist_id: str, tracks: list[dict[str, Any]]) -> None:
    uris = [track["uri"] for track in tracks]
    for index in range(0, len(uris), 100):
        spotify_post(f"/playlists/{playlist_id}/tracks", access_token, {"uris": uris[index : index + 100]})


@app.route("/")
def index():
    return render_template_string(PAGE, authenticated=authenticated(), message="", error="")


@app.route("/login")
def login():
    try:
        require_spotify_config()
    except RuntimeError as error:
        return render_template_string(PAGE, authenticated=False, message="", error=str(error)), 500

    state = secrets.token_urlsafe(24)
    session["spotify_state"] = state
    params = {
        "client_id": Config.spotify_client_id,
        "response_type": "code",
        "scope": SPOTIFY_SCOPE,
        "redirect_uri": Config.redirect_uri,
        "state": state,
        "show_dialog": True,
    }
    return redirect(f"{SPOTIFY_AUTH_URL}?{urllib.parse.urlencode(params)}")


@app.route("/callback")
def callback():
    if request.args.get("error"):
        return render_template_string(PAGE, authenticated=False, message="", error=request.args["error"]), 400
    if request.args.get("state") != session.get("spotify_state"):
        return render_template_string(PAGE, authenticated=False, message="", error="Spotify state mismatch."), 400

    token_info = token_request(
        {
            "code": request.args["code"],
            "grant_type": "authorization_code",
            "redirect_uri": Config.redirect_uri,
        }
    )
    save_token(token_info)
    return redirect(url_for("index"))


@app.route("/create-playlist", methods=["POST"])
def create_playlist():
    try:
        access_token = get_access_token()
        story_text = request.form["story_text"].strip()
        genre = request.form.get("genre", "").strip()
        if not story_text:
            raise RuntimeError("Please enter scene text first.")

        analysis = call_ollama(story_text, genre)
        sources = source_playlists(access_token, analysis)
        tracks = aggregate_tracks(sources, target_size=Config.playlist_size)
        if not tracks:
            raise RuntimeError("Spotify did not return enough matching tracks. Try a broader genre or scene.")

        user_id = get_user_id(access_token)
        description = (
            f"MusiWrite: {analysis.mood} {analysis.scene}; "
            f"built from {len(sources)} source playlists with duplicate tracks removed."
        )
        playlist_id = create_spotify_playlist(access_token, user_id, analysis.playlist_title, description)
        add_tracks(access_token, playlist_id, tracks)
        playlist_url = f"https://open.spotify.com/playlist/{playlist_id}"
        message = Markup(
            "<strong>{}</strong> created with {} tracks. "
            "Mood: <code>{}</code>; scene: <code>{}</code>. "
            "<a href='{}'>Open in Spotify</a>"
        ).format(analysis.playlist_title, len(tracks), analysis.mood, analysis.scene, playlist_url)
        return render_template_string(PAGE, authenticated=True, message=message, error="")
    except Exception as error:
        return render_template_string(PAGE, authenticated=authenticated(), message="", error=str(error)), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
