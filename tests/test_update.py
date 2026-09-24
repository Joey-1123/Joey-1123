"""Offline tests for update.py (no network; requests is mocked)."""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update as u


def test_in_scope():
    assert u.in_scope({"name": "Joey-1123/a", "isFork": False})
    assert not u.in_scope({"name": "Joey-1123/forked", "isFork": True})
    assert u.in_scope({"name": "Joey-1123/FlickerX", "isFork": True})


def test_in_scope_excluded():
    u.EXCLUDED_REPOS.add("Joey-1123/a")
    try:
        assert not u.in_scope({"name": "Joey-1123/a", "isFork": False})
    finally:
        u.EXCLUDED_REPOS.clear()


def test_format_loc():
    assert u.format_loc(999) == "999"
    assert u.format_loc(999999) == "999,999"
    assert u.format_loc(1407583) == "1.4M"


def test_calculate_age_shape():
    s, b = u.calculate_age()
    assert isinstance(s, str) and s
    assert isinstance(b, bool)


def test_load_cache_corrupt(tmp_path, monkeypatch):
    p = tmp_path / "bad.json"
    p.write_text("{bad")
    monkeypatch.setattr(u, "CACHE_PATH", str(p))
    assert u.load_cache() == {}


def test_update_svg_roundtrip_keeps_values_and_width():
    for theme in ["light_mode.svg", "dark_mode.svg"]:
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), theme)
        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as tf:
            dst = tf.name
        try:
            shutil.copy(src, dst)
            import xml.etree.ElementTree as ET
            t = ET.parse(dst)
            r = t.getroot()
            ns = {"svg": "http://www.w3.org/2000/svg"}
            assert r.attrib.get("width") == "985px", f"{theme} width must be 985px"

            def g(i):
                el = r.find(f".//svg:*[@id='{i}']", ns)
                assert el is not None, f"missing #{i} in {theme}"
                return el.text

            stats = {
                "age_display": g("age_data"), "repos": g("repo_data"),
                "stars": g("star_data"), "contributed": g("contrib_data"),
                "commits": g("commit_data"), "followers": g("follower_data"),
                "prs": "12", "issues": "5", "top_langs": "Python 42%",
                "top_repos": ["1. a ★12 · Python", "—", "—", "—", "—"],
                "loc": g("loc_data"),
                "loc_add": int(g("loc_add").replace(",", "")),
                "loc_del": int(g("loc_del").replace(",", "").lstrip("-")),
            }
            u.update_svg(dst, stats)
            out = open(dst).read()
            assert "ns0:" not in out
            assert 'width="985px"' in out
            for v in [stats["repos"], stats["stars"], stats["commits"],
                      "12", "5", "Python 42%", "1. a ★12 · Python"]:
                assert str(v) in out
        finally:
            os.unlink(dst)


def test_aggregate_languages():
    nodes = [
        {"name": "a", "languages": [("Python", 100), ("C++", 50)]},
        {"name": "b", "languages": [("Python", 200), ("JavaScript", 300)]},
        {"name": "c", "languages": []},
    ]
    assert u.aggregate_languages(nodes) == ["Python", "JavaScript", "C++"]
    assert u.aggregate_languages(nodes, top_n=2) == ["Python", "JavaScript"]
    assert u.aggregate_languages([]) == []


def test_language_shares():
    nodes = [
        {"name": "a", "languages": [("Python", 100), ("C++", 50)]},
        {"name": "b", "languages": [("Python", 200), ("JavaScript", 300)]},
    ]
    shares = u.language_shares(nodes)
    assert [n for n, _ in shares] == ["Python", "JavaScript", "C++"]
    total = sum(p for _, p in shares)
    assert 99 <= total <= 101  # rounding tolerance
    assert u.language_shares([]) == []
    assert u.language_shares([{"name": "x", "languages": []}]) == []


def test_top_repos():
    nodes = [
        {"name": "Joey-1123/b", "stars": 3, "languages": [("Python", 10)]},
        {"name": "Joey-1123/a", "stars": 12, "languages": []},
        {"name": "Joey-1123/c", "stars": 7, "languages": [("JS", 5)]},
    ]
    top = u.top_repos(nodes, top_n=2)
    assert top[0]["name"] == "a" and top[0]["stars"] == 12 and top[0]["lang"] == "—"
    assert top[1]["name"] == "c" and top[1]["lang"] == "JS"
    long_ = {"name": "Joey-1123/" + "x" * 40, "stars": 99, "languages": []}
    assert len(u.top_repos([long_])[0]["name"]) <= 25
    assert u.top_repos([]) == []


def test_format_top_repo():
    assert u.format_top_repo(1, {"name": "a", "stars": 12, "lang": "Python"}) == "1. a ★12 · Python"
