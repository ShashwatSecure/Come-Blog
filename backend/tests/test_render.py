from app import render
from app.domain import ImageAsset, Section
from tests.conftest import make_article


def test_markdown_escapes_html_and_blocks_javascript_links():
    html = render.markdown_to_html('<script>alert(1)</script> [x](javascript:alert(1)) [ok](https://a.com/p)')
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert 'href="javascript' not in html
    assert 'href="https://a.com/p"' in html and 'rel="noopener noreferrer"' in html


def test_markdown_lists_bold_and_citations():
    html = render.markdown_to_html("Intro **bold** claim [1].\n\n- one\n- two\n\n1. first\n2. second", {1})
    assert "<strong>bold</strong>" in html
    assert '<sup class="cite"><a href="#source-1"' in html
    assert "<ul><li>one</li><li>two</li></ul>" in html and "<ol><li>first</li>" in html


def test_unknown_citation_is_dropped_not_linked():
    assert "source-7" not in render.markdown_to_html("Claim [7].", {1})


def test_article_page_has_seo_structure_links_and_sources(article):
    page = render.article_page(article)
    assert page.count("<h1>") == 1
    assert '<meta name="description"' in page and 'rel="canonical"' in page
    assert "application/ld+json" in page and "BlogPosting" in page
    assert 'id="source-1"' in page and "https://en.wikipedia.org/wiki/Alpha" in page
    assert 'href="#schedule"' in page and 'id="schedule"' in page
    assert "prefers-color-scheme" in render.STYLE_CSS


def test_article_page_escapes_hostile_title_and_closes_json_ld(sources):
    evil = make_article(sources, title='</script><img src=x onerror=alert(1)>', tags=["a"])
    page = render.article_page(evil)
    assert "<img src=x onerror" not in page
    assert "\\u003c/script\\u003e" in page  # JSON-LD cannot close its own script tag
    assert page.count("</script>") == page.count("<script")


def test_hero_image_rendered_with_credit_and_alt(sources):
    img = ImageAsset(url="https://upload.wikimedia.org/a.jpg", alt="A bed", credit="Jane, CC BY, via Wikimedia Commons",
                     credit_url="https://commons.wikimedia.org/wiki/File:a.jpg", filename="image-1.jpg")
    page = render.article_page(make_article(sources, images=[img]))
    assert 'src="image-1.jpg"' in page and 'alt="A bed"' in page and "Jane, CC BY" in page


def test_generated_cover_used_when_no_photo(article):
    page = render.article_page(article)
    assert 'src="cover.svg"' in page
    svg = render.cover_svg(article)
    assert svg.startswith("<svg") and "Sleep Better Tonight" in svg and "<script" not in svg


def test_cover_svg_escapes_hostile_titles(sources):
    svg = render.cover_svg(make_article(sources, title='<script>alert(1)</script> & "quotes"'))
    assert "<script>" not in svg and "&lt;script&gt;" in svg


def test_markdown_export_has_linked_citations_and_sources(article):
    md = render.to_markdown(article)
    assert md.startswith("# Sleep Better Tonight")
    assert "[[1](https://en.wikipedia.org/wiki/Alpha)]" in md
    assert "## Sources" in md and "1. [Alpha - Wikipedia]" in md


def test_index_feed_and_sitemap(article):
    assert "posts/sleep-better/index.html" in render.index_page([article])
    assert "No posts yet" in render.index_page([])
    assert "<item>" in render.rss_feed([article]) and "<loc>" in render.sitemap([article])


def test_sections_need_unique_anchor_ids(sources):
    article = make_article(sources, sections=[Section(id="x", heading="One", body_md="a"), Section(id="y", heading="Two", body_md="b")])
    page = render.article_page(article)
    assert page.count('id="x"') == 1 and page.count('id="y"') == 1
