import pytest

from app import research
from app.config import settings
from app.domain import Article, ImageAsset, ResearchBundle, Section, Source


@pytest.fixture(autouse=True)
def isolated_site(tmp_path, monkeypatch):
    """Every test writes to its own output dir and never touches the network."""
    monkeypatch.setattr(settings, "output_dir", str(tmp_path / "output"))
    monkeypatch.setattr(settings, "tavily_api_key", "")
    monkeypatch.setattr(settings, "download_images", False)
    research.clear_cache()
    yield


@pytest.fixture
def sources():
    return [
        Source(id=1, title="Alpha - Wikipedia", url="https://en.wikipedia.org/wiki/Alpha", snippet="Alpha facts.", provider="wikipedia"),
        Source(id=2, title="Beta guide", url="https://www.example.com/beta", snippet="Beta facts.", provider="tavily"),
    ]


@pytest.fixture
def bundle(sources):
    return ResearchBundle(
        topic="sleep hygiene", summary="Sleep matters.", sources=sources,
        images=[ImageAsset(url="https://upload.wikimedia.org/x.jpg", alt="Bed", credit="A, CC BY, via Wikimedia Commons", credit_url="https://commons.wikimedia.org/wiki/File:x.jpg")],
        providers=["tavily", "wikipedia"],
    )


def make_article(sources, **overrides) -> Article:
    body = ("Consistent sleep schedules help the body regulate its internal clock [1]. "
            "Cool dark rooms improve sleep quality for most adults [2]. " * 2)
    defaults = dict(
        slug="sleep-better", topic="sleep hygiene", title="Sleep Better Tonight", subtitle="Small habits, big rest.",
        excerpt="Practical, evidence-based habits that improve how well and how long you sleep every night.",
        tags=["sleep", "health"],
        sections=[Section(id="schedule", heading="Keep a schedule", body_md=body),
                  Section(id="room", heading="Fix your room", body_md=body)],
        takeaways=["Keep a schedule", "Cool the room", "Limit screens"], closing="Start tonight.", sources=sources,
    )
    defaults.update(overrides)
    return Article(**defaults)


@pytest.fixture
def article(sources):
    return make_article(sources)
