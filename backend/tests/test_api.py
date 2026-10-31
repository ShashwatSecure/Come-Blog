import time

import pytest
from fastapi.testclient import TestClient

from app import runs, security, store
from app.config import settings
from tests.conftest import make_article


@pytest.fixture
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(runs, "_manager", None)
    security.limiter._hits.clear()
    with TestClient(app) as c:
        yield c
    if runs._manager is not None:  # let background jobs finish before pytest closes the log stream
        runs._manager._pool.shutdown(wait=True)


def _seed(sources, **kw):
    return store.save_article(make_article(sources, **kw), [])


def test_openapi_spec_documents_every_route(client):
    spec = client.get("/openapi.json").json()
    assert spec["openapi"].startswith("3.") and spec["info"]["title"] == "Come-Blog API"
    assert client.get("/docs").status_code == 200 and client.get("/redoc").status_code == 200

    expected = {("get", "/health"), ("get", "/ollama/check"), ("post", "/preview"), ("post", "/blogs"), ("get", "/jobs/{job_id}"),
                ("get", "/posts"), ("get", "/posts/{slug}"), ("get", "/posts/{slug}/markdown"), ("delete", "/posts/{slug}")}
    found = {(method, path) for path, ops in spec["paths"].items() for method in ops}
    assert found == expected  # the site mount and the redirect stay out of the spec

    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert op.get("tags") and op.get("summary"), f"{method} {path} lacks tags or summary"


def test_openapi_declares_api_key_scheme_and_error_models(client):
    spec = client.get("/openapi.json").json()
    scheme = spec["components"]["securitySchemes"]["APIKeyHeader"]
    assert scheme["in"] == "header" and scheme["name"] == "X-API-Key"
    assert "security" not in spec["paths"]["/health"]["get"]  # liveness stays open
    assert spec["paths"]["/blogs"]["post"]["security"]
    assert spec["paths"]["/blogs"]["post"]["responses"]["202"]
    assert {"401", "429", "422"} <= set(spec["paths"]["/blogs"]["post"]["responses"])
    assert "404" in spec["paths"]["/posts/{slug}"]["get"]["responses"]
    assert spec["components"]["schemas"]["CreateBlogRequest"]["properties"]["length"]["enum"] == ["short", "medium", "long"]


def test_api_key_still_enforced_after_security_scheme(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "s3cret")
    assert client.get("/posts").status_code == 401
    assert client.get("/posts", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/posts", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_health_and_security_headers(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-request-id"]


def test_posts_crud_and_site_is_served(client, sources):
    saved = _seed(sources)
    listing = client.get("/posts").json()
    assert listing["stats"]["posts"] == 1 and listing["posts"][0]["slug"] == saved.slug
    assert client.get(f"/posts/{saved.slug}").json()["title"] == "Sleep Better Tonight"
    md = client.get(f"/posts/{saved.slug}/markdown")
    assert md.status_code == 200 and md.text.startswith("# Sleep Better Tonight")
    page = client.get(f"/site/posts/{saved.slug}/index.html")
    assert page.status_code == 200 and "Content-Security-Policy" in page.headers
    assert client.get("/site/index.html").status_code == 200
    assert client.delete(f"/posts/{saved.slug}").status_code == 204
    assert client.get(f"/posts/{saved.slug}").status_code == 404


def test_path_traversal_is_rejected(client):
    assert client.get("/posts/..%2F..%2Fetc").status_code == 404
    assert client.delete("/posts/..").status_code in (404, 405)
    assert store.load_article("../x") is None


def test_duplicate_titles_get_unique_slugs(sources):
    a, b = _seed(sources), _seed(sources)
    assert a.slug == "sleep-better" and b.slug == "sleep-better-2"


def test_api_key_is_enforced_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "s3cret")
    assert client.get("/posts").status_code == 401
    assert client.get("/posts", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/posts", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open for probes


def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)
    codes = [client.post("/preview", json={"topic": "ab"}).status_code for _ in range(3)]
    assert codes[-1] == 429
    assert "retry-after" in client.post("/preview", json={"topic": "ab"}).headers


def test_validation_rejects_bad_input(client):
    assert client.post("/blogs", json={"topic": "x"}).status_code == 422
    assert client.post("/blogs", json={"topic": "valid topic", "length": "huge"}).status_code == 422
    assert client.post("/blogs", json={"topic": "a" * 301}).status_code == 422


def test_job_lifecycle_with_stubbed_graph(client, monkeypatch, sources):
    article = make_article(sources)

    class FakeGraph:
        def invoke(self, state, config):
            config["configurable"]["event_sink"]({"stage": "research", "message": "Researching"})
            return {"article": article}

    monkeypatch.setattr(runs, "build_graph", lambda: FakeGraph())
    created = client.post("/blogs", json={"topic": "sleep hygiene"})
    assert created.status_code == 202
    job_id = created.json()["id"]
    for _ in range(50):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done" and job["url"] == "/site/posts/sleep-better/index.html"
    assert job["progress"] == 1.0 and job["events"][0]["stage"] == "research"
    assert client.get("/jobs/nope").status_code == 404


def test_failed_job_reports_error_without_traceback(client, monkeypatch):
    class Boom:
        def invoke(self, state, config):
            raise RuntimeError("model exploded")

    monkeypatch.setattr(runs, "build_graph", lambda: Boom())
    job_id = client.post("/blogs", json={"topic": "sleep hygiene"}).json()["id"]
    for _ in range(50):
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] == "failed":
            break
        time.sleep(0.05)
    assert job["status"] == "failed" and "model exploded" in job["error"] and "Traceback" not in job["error"]


def test_queue_full_returns_429(client, monkeypatch):
    monkeypatch.setattr(settings, "max_queued_jobs", 1)

    class Slow:
        def invoke(self, state, config):
            time.sleep(0.5)
            raise RuntimeError("stop")

    monkeypatch.setattr(runs, "build_graph", lambda: Slow())
    assert client.post("/blogs", json={"topic": "first topic"}).status_code == 202
    assert client.post("/blogs", json={"topic": "second topic"}).status_code == 429
