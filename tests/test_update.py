import datetime
import json
import sys
import xml.etree.ElementTree as etree
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import update

SVG_NS = "{http://www.w3.org/2000/svg}"


class FakeResponse:
    def __init__(self, status_code=200, data=None, headers=None):
        self.status_code = status_code
        self._data = data
        self.headers = headers or {}

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


def test_fetch_repo_loc_uses_positive_deletions(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, [[1, 100, -40], [2, 50, -10]])

    monkeypatch.setattr(update.requests, "get", fake_get)
    assert update.fetch_repo_loc("owner/repo") == (150, 50)


def test_fetch_repo_loc_failure_returns_none(monkeypatch):
    monkeypatch.setattr(
        update.requests, "get", lambda *a, **k: FakeResponse(404, {})
    )
    assert update.fetch_repo_loc("owner/missing") is None


def test_fetch_repo_loc_retries_computing_then_succeeds(monkeypatch):
    responses = [FakeResponse(202), FakeResponse(200, [[1, 5, -2]])]
    monkeypatch.setattr(update.requests, "get", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(update.time, "sleep", lambda s: None)
    assert update.fetch_repo_loc("owner/repo") == (5, 2)


def test_fetch_user_loc_uses_absolute_deletions(monkeypatch):
    payload = [
        {"author": {"login": "Joey-1123"}, "weeks": [{"a": 10, "d": -4}]},
        {"author": {"login": "someone"}, "weeks": [{"a": 1, "d": -1}]},
    ]
    monkeypatch.setattr(update.requests, "get", lambda *a, **k: FakeResponse(200, payload))
    assert update.fetch_user_loc("owner/repo") == (10, 4)


def _nodes(*names):
    return [{"name": name, "commits": 1, "isFork": False} for name in names]


def test_get_loc_data_does_not_cache_failures(tmp_path, monkeypatch):
    cache_path = tmp_path / "cache" / "loc.json"
    monkeypatch.setattr(update, "CACHE_PATH", str(cache_path))
    monkeypatch.setattr(update.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        update,
        "fetch_repo_loc",
        lambda name: None if name == "b/b" else (10, 4),
    )
    monkeypatch.setattr(update, "fetch_user_loc", lambda name: (8, 3))

    additions, deletions, net, user = update.get_loc_data(_nodes("a/a", "b/b"))

    assert (additions, deletions, net) == (10, 4, 6)
    assert user[2] == 5

    cached = json.loads(cache_path.read_text())
    assert "a/a" in cached
    assert "b/b" not in cached


def test_get_loc_data_falls_back_to_repo_wide(monkeypatch):
    monkeypatch.setattr(update, "CACHE_PATH", "")
    monkeypatch.setattr(update.time, "sleep", lambda s: None)
    monkeypatch.setattr(update, "fetch_repo_loc", lambda name: (10, 4))
    monkeypatch.setattr(
        update,
        "fetch_user_loc",
        lambda name: (8, 3) if name == "a/a" else None,
    )

    additions, deletions, net, user = update.get_loc_data(
        _nodes("a/a", "b/b"), use_cache=False
    )

    assert (additions, deletions, net) == (20, 8, 12)
    assert user[2] is None


def test_in_scope_excludes_forks_unless_included(monkeypatch):
    monkeypatch.setattr(update, "INCLUDED_FORKS", {"owner/keep"})

    assert update.in_scope({"name": "owner/own", "isFork": False})
    assert not update.in_scope({"name": "owner/fork", "isFork": True})
    assert update.in_scope({"name": "owner/keep", "isFork": True})


def test_calculate_age_january_boundary(monkeypatch):
    monkeypatch.setattr(update, "BIRTHDAY", datetime.date(2000, 1, 20))

    label, is_birthday = update.calculate_age(datetime.date(2026, 1, 10))

    assert label == "25 years, 11 months, 21 days"
    assert is_birthday is False


def test_calculate_age_birthday(monkeypatch):
    monkeypatch.setattr(update, "BIRTHDAY", datetime.date(2005, 5, 1))

    label, is_birthday = update.calculate_age(datetime.date(2026, 5, 1))

    assert label == "21 years"
    assert is_birthday is True


def test_format_loc():
    assert update.format_loc(999) == "999"
    assert update.format_loc(1_500_000) == "1.5M"
    assert update.format_loc(-1234) == "-1,234"


def test_load_cache_corrupt(tmp_path, monkeypatch):
    cache_path = tmp_path / "loc.json"
    cache_path.write_text("{not json")
    monkeypatch.setattr(update, "CACHE_PATH", str(cache_path))

    assert update.load_cache() == {}


def test_update_svg_roundtrip_keeps_values_and_a11y(tmp_path):
    svg_path = tmp_path / "card.svg"
    svg_path.write_bytes((ROOT / "light_mode.svg").read_bytes())

    stats = {
        "age_display": "21 years",
        "repos": 39,
        "stars": 2,
        "contributed": 42,
        "commits": 4298,
        "followers": 5,
        "loc": "1.2M",
        "loc_add": 1234567,
        "loc_del": 34567,
    }
    update.update_svg(str(svg_path), stats)

    tree = etree.parse(str(svg_path))
    root = tree.getroot()

    assert root.get("viewBox") == "0 0 1800 520"
    assert root.get("role") == "img"
    assert root.find(f".//{SVG_NS}title") is not None
    assert root.find(f".//{SVG_NS}desc") is not None

    def text(elem_id):
        return root.find(f".//{SVG_NS}*[@id='{elem_id}']").text

    assert text("loc_add") == "1,234,567"
    assert text("loc_del") == "34,567"
    assert text("loc_data") == "1.2M"
    assert text("age_data") == "21 years"

    raw = svg_path.read_text(encoding="utf-8")
    assert "\u2500" in raw
    assert "\u00e2\u201d\u20ac" not in raw
