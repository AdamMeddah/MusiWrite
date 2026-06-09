# MusiWrite

MusiWrite is a Flask app that turns free-form story or scene text into a private Spotify playlist. It uses a local Ollama model to extract the writing's mood, scene, energy, valence, playlist title, and search phrases, then uses the Spotify Web API to collect matching tracks from multiple playlist sources while removing duplicates.

This project is designed around privacy and cost control: the user's writing is analyzed locally through Ollama instead of being sent to a hosted LLM API.

## Features

- Spotify OAuth flow for creating private playlists on behalf of the authenticated user.
- Local LLM inference through Ollama, with a recommended quantized 7B model.
- Structured mood and scene extraction from unstructured text.
- Spotify playlist search across multiple generated queries.
- Track aggregation from several source playlists with duplicate removal and per-source balancing.
- Fallback heuristic analysis when Ollama is unavailable, so the app can fail gracefully during demos.
- Unit-tested parsing, query generation, and aggregation logic.

## Tech Stack

- Python
- Flask
- Spotify Web API
- Ollama
- Requests
- Pytest

## How It Works

1. The user connects their Spotify account through OAuth.
2. The user submits scene text and an optional genre filter.
3. MusiWrite sends the text to a local Ollama model and asks for compact JSON containing mood, scene, energy, valence, title, genre hints, and Spotify search terms.
4. The app searches Spotify for playlists matching the generated mood and scene queries.
5. Tracks are pulled from several source playlists, deduplicated by Spotify track ID, capped per source, and inserted into a new private Spotify playlist.

## Project Structure

```text
.
|-- main.py                 # Flask routes, Spotify OAuth, Ollama calls, Spotify API integration
|-- musiwrite/
|   |-- __init__.py
|   `-- core.py             # Testable parsing, fallback analysis, search-query, and aggregation logic
|-- tests/
|   `-- test_core.py        # Unit tests for core playlist behavior
|-- .env.example            # Required environment variables
|-- requirements.txt
`-- README.md
```

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Install and start Ollama:

```bash
ollama pull mistral:7b-instruct-q4_0
ollama serve
```

Create a Spotify developer app at the Spotify Developer Dashboard, then add this redirect URI:

```text
http://localhost:5000/callback
```

Create your local environment file:

```bash
cp .env.example .env
```

Fill in:

```text
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
FLASK_SECRET_KEY=...
```

## Run

```bash
python main.py
```

Open:

```text
http://localhost:5000
```

## Test

```bash
python -m pytest tests
```


## Notes

- Playlists are created as private by default.
- The app also supports the older `CLIENT_ID` and `CLIENT_SECRET` variable names for backward compatibility, but `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` are preferred.
- Spotify credentials and Flask secrets should only live in `.env`, which is ignored by git.
