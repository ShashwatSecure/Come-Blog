"""Error paths of the HTTP API: bad input, unknown ids, missing posts and API-key enforcement."""

import pytest

from tests.test_api import client  # noqa: F401  (fixture)

KEY = {"X-API-Key": "s3cret"}


@pytest.mark.parametrize("payload", [
    {},
    {"topic": ""},
    {"topic": "ab"},
    {"topic": "a" * 301},
    {"topic": "valid topic", "length": "huge"},
    {"topic": "valid topic", "tone": "sarcastic-extreme"},
    {"topic": "valid topic", "audience": "x"},
    {"topic": 123},
])
def test_create_blog_rejects_invalid_payloads(client, payload):  # noqa: F811
    assert client.post("/blogs", json=payload).status_code == 422


def test_create_blog_rejects_non_json_body(client):  # noqa: F811
    r = client.post("/blogs", content="not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_preview_rejects_short_topic(client):  # noqa: F811
    assert client.post("/preview", json={"topic": "x"}).status_code == 422


def test_unknown_job_id_returns_404(client):  # noqa: F811
    r = client.get("/jobs/does-not-exist")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown job"


def test_missing_post_returns_404_on_every_verb(client):  # noqa: F811
    assert client.get("/posts/nope").status_code == 404
    assert client.get("/posts/nope/markdown").status_code == 404
    assert client.delete("/posts/nope").status_code == 404


def test_delete_is_not_repeatable(client, sources):  # noqa: F811
    from app import store
    from tests.conftest import make_article

    slug = store.save_article(make_article(sources), []).slug
    assert client.delete(f"/posts/{slug}").status_code == 204
    assert client.delete(f"/posts/{slug}").status_code == 404


@pytest.mark.parametrize("method,path,body", [
    ("get", "/posts", None),
    ("get", "/posts/any", None),
    ("get", "/posts/any/markdown", None),
    ("delete", "/posts/any", None),
    ("get", "/jobs/any", None),
    ("get", "/ollama/check", None),
    ("post", "/preview", {"topic": "valid topic"}),
    ("post", "/blogs", {"topic": "valid topic"}),
])
def test_every_protected_route_requires_the_key(client, monkeypatch, method, path, body):  # noqa: F811
    from app.config import settings

    monkeypatch.setattr(settings, "api_key", "s3cret")
    kwargs = {"json": body} if body is not None else {}
    missing = getattr(client, method)(path, **kwargs)
    wrong = getattr(client, method)(path, headers={"X-API-Key": "wrong"}, **kwargs)
    assert missing.status_code == 401 and wrong.status_code == 401
    assert missing.json()["detail"] == "Invalid or missing API key"


def test_valid_key_unlocks_routes_and_unknown_ids_still_404(client, monkeypatch):  # noqa: F811
    from app.config import settings

    monkeypatch.setattr(settings, "api_key", "s3cret")
    assert client.get("/jobs/any", headers=KEY).status_code == 404
    assert client.get("/posts/any", headers=KEY).status_code == 404
    assert client.delete("/posts/any", headers=KEY).status_code == 404


def test_auth_is_checked_before_validation(client, monkeypatch):  # noqa: F811
    from app.config import settings

    monkeypatch.setattr(settings, "api_key", "s3cret")
    assert client.post("/blogs", json={"topic": "x"}).status_code == 401
    assert client.post("/blogs", json={"topic": "x"}, headers=KEY).status_code == 422


def test_health_is_open_even_with_a_key(client, monkeypatch):  # noqa: F811
    from app.config import settings

    monkeypatch.setattr(settings, "api_key", "s3cret")
    assert client.get("/health").status_code == 200


def test_no_key_configured_means_open_access(client, monkeypatch):  # noqa: F811
    from app.config import settings

    monkeypatch.setattr(settings, "api_key", "")
    assert client.get("/posts").status_code == 200
