# 05 - The blog itself

Baseline output: a Markdown file with a heading and one paragraph.
New output: a self-contained static site in `output/site/`.

```
output/site/
  index.html          card grid of all posts
  feed.xml            RSS 2.0 (latest 30)
  sitemap.xml
  404.html
  stats.json
  assets/style.css    one shared stylesheet
  posts/<slug>/
    index.html        the article
    article.md        portable Markdown with linked citations
    article.json      full data: sections, sources, quality, attempts
    cover.svg         generated cover art
    image-1.jpg ...   downloaded, licensed photos (when found)
```

## Reading experience

- Serif body at ~68ch measure, system sans for UI; fluid heading sizes.
- Sticky header, reading-progress bar, sticky table of contents with the current
  section highlighted (IntersectionObserver), collapses on small screens.
- Key-takeaways box, byline with date, reading time and word count.
- Hero photo with credit, or generated SVG cover; a second photo is placed
  between sections when available.
- Superscript citations linking to a numbered Sources list.
- Editorial-checks footer showing checks passed, reviewer score, writing passes
  and models used, so readers can see how the post was made.
- Tag chips, "Needs human review" badge when the quality bar was not met.

## Quality of the page itself

- Light and dark themes via `prefers-color-scheme`.
- Responsive grid and layout (mobile first), print stylesheet, reduced-motion
  support, skip link, semantic landmarks, alt text on every image, lazy loading.
- SEO and sharing: `<title>`, meta description, canonical URL, Open Graph and
  Twitter card tags, `BlogPosting` JSON-LD including citations, RSS and sitemap.
- No external fonts, scripts or CDNs: nothing loads from third parties.

## Not verified

The pages were validated through string-level tests only (structure, escaping,
links, SEO tags). They have not been opened in a browser or checked with an
accessibility tool, so visual polish and contrast are unconfirmed. The next
step is to open `output/site/index.html` and review it by eye.
