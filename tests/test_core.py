from musiwrite.core import aggregate_tracks, build_search_queries, fallback_analysis, parse_scene_analysis


def test_parse_scene_analysis_from_json():
    analysis = parse_scene_analysis(
        """
        {
          "mood": "Urgent",
          "scene": "rainy rooftop chase",
          "energy": 0.9,
          "valence": 0.2,
          "genres": ["Synthwave"],
          "playlist_title": "Neon Betrayal",
          "search_terms": ["dark synthwave chase", "rainy night drive"]
        }
        """,
        default_genre="electronic",
    )

    assert analysis.mood == "urgent"
    assert analysis.scene == "rainy rooftop chase"
    assert analysis.energy == 0.9
    assert analysis.valence == 0.2
    assert analysis.genres == ["electronic", "synthwave"]
    assert analysis.playlist_title == "Neon Betrayal"


def test_parse_legacy_comma_response():
    analysis = parse_scene_analysis("Calm, Jazz, Midnight Study")

    assert analysis.mood == "calm"
    assert analysis.genres == ["jazz"]
    assert analysis.playlist_title == "Midnight Study"


def test_build_search_queries_deduplicates_terms():
    analysis = fallback_analysis("The hero runs through rain after a betrayal.", "Rock")
    queries = build_search_queries(analysis)

    assert len(queries) == len(set(query.lower() for query in queries))
    assert any("rock" in query.lower() for query in queries)


def test_aggregate_tracks_limits_and_deduplicates():
    sources = [
        {
            "name": "source one",
            "tracks": [
                {"id": "1", "uri": "spotify:track:1", "name": "A"},
                {"id": "2", "uri": "spotify:track:2", "name": "B"},
            ],
        },
        {
            "name": "source two",
            "tracks": [
                {"id": "2", "uri": "spotify:track:2", "name": "B Duplicate"},
                {"id": "3", "uri": "spotify:track:3", "name": "C"},
            ],
        },
    ]

    tracks = aggregate_tracks(sources, target_size=3, per_source_limit=2)

    assert [track["id"] for track in tracks] == ["1", "2", "3"]
