"""Research layer tests: providers are stubbed at the HTTP seam, never the network."""

import pytest

from app import images, research
from app.config import settings
from app.domain import ImageAsset


def _wiki_payload():
    return {"query": {"pages": [
        {"index": 1, "title": "Sleep hygiene", "extract": "Sleep hygiene is a set of habits for better sleep quality.",
         "fullurl": "https://en.wikipedia.org/wiki/Sleep_hygiene",
         "thumbnail": {"source": "https://upload.wikimedia.org/t.jpg", "width": 1200, "height": 800}},
        {"index": 2, "title": "Sleep (disambiguation)", "extract": "Sleep may refer to: many things", "fullurl": "https://x"},
        {"index": 3, "title": "Unrelated", "extract": "Completely different subject about volcanoes.", "fullurl": "https://y"},
    ]}}


def _commons_payload():
    return {"query": {"pages": [
        {"index": 1, "title": "File:Bedroom_night.jpg", "imageinfo": [{
            "mime": "image/jpeg", "width": 3000, "height": 2000, "thumburl": "https://upload.wikimedia.org/c.jpg",
            "thumbwidth": 1200, "thumbheight": 800, "descriptionurl": "https://commons.wikimedia.org/wiki/File:Bedroom_night.jpg",
            "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<a href='x'>Jane</a>"}}}]},
        {"index": 2, "title": "File:Nonfree.jpg", "imageinfo": [{
            "mime": "image/jpeg", "width": 3000, "height": 2000, "thumburl": "https://upload.wikimedia.org/n.jpg",
            "extmetadata": {"LicenseShortName": {"value": "Fair use"}}}]},
        {"index": 3, "title": "File:Tiny.jpg", "imageinfo": [{
            "mime": "image/jpeg", "width": 100, "height": 100, "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]},
    ]}}


@pytest.fixture
def stub_http(monkeypatch):
    calls = []

    def fake_get(url, params):
        calls.append(url)
        return _commons_payload() if "commons" in url else _wiki_payload()

    monkeypatch.setattr(research, "_get_json", fake_get)
    return calls


def test_keyword_query_drops_filler_words():
    assert research.keyword_query("How to improve your sleep hygiene?") == "improve sleep hygiene"


def test_research_merges_filters_and_numbers_sources(stub_http):
    bundle = research.research("sleep hygiene")
    assert [s.id for s in bundle.sources] == [1]
    assert bundle.sources[0].url == "https://en.wikipedia.org/wiki/Sleep_hygiene"
    assert bundle.summary.startswith("Sleep hygiene is")
    assert [i.url for i in bundle.images][0] == "https://upload.wikimedia.org/c.jpg"  # open-licensed, large, preferred
    assert all("Fair use" not in i.credit for i in bundle.images)
    assert "Jane, CC BY-SA 4.0, via Wikimedia Commons" in bundle.images[0].credit


def test_research_is_cached(stub_http):
    research.research("sleep hygiene")
    first = len(stub_http)
    research.research("Sleep Hygiene")
    assert len(stub_http) == first


def test_research_degrades_when_every_provider_fails(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("down")

    monkeypatch.setattr(research, "_get_json", boom)
    bundle = research.research("anything at all")
    assert not bundle.available and bundle.sources == [] and bundle.images == []


def test_tavily_results_come_first_and_are_deduped(monkeypatch, stub_http):
    monkeypatch.setattr(settings, "tavily_api_key", "test-key")
    seen = {}

    def fake_post(url, payload, headers=None):
        seen["auth"] = headers["Authorization"]
        return {"answer": "Fresh answer.", "results": [
            {"title": "Fresh", "url": "https://news.example.com/a", "content": "Fresh content"},
            {"title": "Wiki dup", "url": "https://en.wikipedia.org/wiki/Sleep_hygiene/", "content": "dup"},
        ]}

    monkeypatch.setattr(research, "_post_json", fake_post)
    bundle = research.research("sleep hygiene")
    assert seen["auth"] == "Bearer test-key"
    assert bundle.summary == "Fresh answer."
    assert [s.provider for s in bundle.sources] == ["tavily", "tavily"]
    assert len({s.url.rstrip("/") for s in bundle.sources}) == len(bundle.sources)


def test_image_fetch_rejects_untrusted_hosts_and_non_https():
    assert images.fetch_image("https://evil.example.com/a.jpg") is None
    assert images.fetch_image("http://upload.wikimedia.org/a.jpg") is None
    assert images.fetch_image("file:///etc/passwd") is None


def test_download_images_sniffs_content_type(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "download_images", True)
    payloads = {"https://upload.wikimedia.org/ok.jpg": b"\xff\xd8\xff" + b"0" * 50,
                "https://upload.wikimedia.org/fake.jpg": b"<html>not an image</html>"}
    monkeypatch.setattr(images, "fetch_image", lambda url: payloads[url])
    candidates = [ImageAsset(url=u, alt="a") for u in payloads]
    saved = images.download_images(candidates, tmp_path / "post")
    assert [i.filename for i in saved] == ["image-1.jpg"]
    assert (tmp_path / "post" / "image-1.jpg").read_bytes().startswith(b"\xff\xd8\xff")
