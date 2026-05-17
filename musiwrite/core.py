from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SceneAnalysis:
    mood: str
    scene: str
    energy: float
    valence: float
    genres: list[str] = field(default_factory=list)
    playlist_title: str = "MusiWrite Playlist"
    search_terms: list[str] = field(default_factory=list)


def clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.5
    return max(low, min(high, number))


def clean_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+", " ", text) if text else fallback


def normalize_genres(genres: Any, default_genre: str = "") -> list[str]:
    if isinstance(genres, str):
        raw_genres = [genres]
    elif isinstance(genres, list):
        raw_genres = genres
    else:
        raw_genres = []

    cleaned = []
    if default_genre:
        cleaned.append(default_genre.strip().lower())
    for genre in raw_genres:
        label = clean_text(genre, "").lower()
        if label and label not in cleaned:
            cleaned.append(label)
    return cleaned[:3]


def extract_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in LLM output.")
    return json.loads(match.group(0))


def parse_scene_analysis(raw_text: str, default_genre: str = "") -> SceneAnalysis:
    try:
        data = extract_json(raw_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return parse_legacy_response(raw_text, default_genre)

    mood = clean_text(data.get("mood"), "atmospheric").lower()
    scene = clean_text(data.get("scene"), "story scene").lower()
    genres = normalize_genres(data.get("genres"), default_genre)
    title = clean_text(data.get("playlist_title"), f"{mood.title()} Scene Mix")[:48]
    search_terms = [clean_text(term, "") for term in data.get("search_terms", []) if clean_text(term, "")]

    return SceneAnalysis(
        mood=mood,
        scene=scene,
        energy=clamp(data.get("energy")),
        valence=clamp(data.get("valence")),
        genres=genres,
        playlist_title=title,
        search_terms=search_terms[:6],
    )


def parse_legacy_response(raw_text: str, default_genre: str = "") -> SceneAnalysis:
    parts = [part.strip().strip('"') for part in str(raw_text or "").split(",") if part.strip()]
    mood = clean_text(parts[0] if parts else "", "atmospheric").lower()
    if len(parts) >= 3:
        genre = parts[1]
        title = parts[2]
    elif len(parts) == 2:
        genre = default_genre
        title = parts[1]
    else:
        genre = default_genre
        title = f"{mood.title()} Scene Mix"
    return SceneAnalysis(
        mood=mood,
        scene="story scene",
        energy=0.5,
        valence=0.5,
        genres=normalize_genres([genre], default_genre),
        playlist_title=clean_text(title, f"{mood.title()} Scene Mix")[:48],
    )


def fallback_analysis(story_text: str, genre: str = "") -> SceneAnalysis:
    lowered = story_text.lower()
    intense_words = {"fight", "chase", "battle", "escape", "panic", "racing", "revenge", "storm"}
    dark_words = {"betray", "grief", "alone", "dark", "loss", "fear", "rain", "haunted"}
    bright_words = {"sun", "hope", "love", "calm", "warm", "victory", "home"}

    intensity = sum(word in lowered for word in intense_words)
    darkness = sum(word in lowered for word in dark_words)
    brightness = sum(word in lowered for word in bright_words)

    if intensity:
        mood = "urgent"
        energy = 0.85
    elif darkness > brightness:
        mood = "melancholic"
        energy = 0.45
    elif brightness:
        mood = "hopeful"
        energy = 0.6
    else:
        mood = "cinematic"
        energy = 0.55

    valence = clamp(0.5 + (brightness * 0.15) - (darkness * 0.12))
    scene = " ".join(re.findall(r"[a-zA-Z]{4,}", story_text)[:4]).lower() or "story scene"
    return SceneAnalysis(
        mood=mood,
        scene=scene,
        energy=energy,
        valence=valence,
        genres=normalize_genres([genre], genre),
        playlist_title=f"{mood.title()} Scene Mix",
        search_terms=[],
    )


def build_search_queries(analysis: SceneAnalysis) -> list[str]:
    genre = analysis.genres[0] if analysis.genres else ""
    candidates = [
        *analysis.search_terms,
        f"{analysis.mood} {genre} playlist",
        f"{analysis.scene} {genre} soundtrack",
        f"{analysis.mood} {analysis.scene}",
        f"{analysis.mood} cinematic playlist",
    ]
    queries = []
    for candidate in candidates:
        query = re.sub(r"\s+", " ", candidate).strip()
        if query and query.lower() not in {item.lower() for item in queries}:
            queries.append(query)
    return queries[:8]


def aggregate_tracks(source_playlists: list[dict[str, Any]], target_size: int = 40, per_source_limit: int = 12) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_track_ids: set[str] = set()

    for source in source_playlists:
        accepted_from_source = 0
        for track in source.get("tracks", []):
            track_id = track.get("id")
            uri = track.get("uri")
            if not track_id or not uri or track_id in seen_track_ids:
                continue
            selected.append(track)
            seen_track_ids.add(track_id)
            accepted_from_source += 1
            if len(selected) >= target_size or accepted_from_source >= per_source_limit:
                break
        if len(selected) >= target_size:
            break

    return selected[:target_size]
