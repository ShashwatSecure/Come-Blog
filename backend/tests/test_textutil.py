from app.textutil import (
    clamp_text,
    clean_llm_markdown,
    clean_takeaways,
    coverage,
    make_slug,
    sentences,
    unique_ratio,
)


def test_clean_llm_markdown_strips_preamble_headings_and_fences():
    raw = "Sure, here is the section:\n\n## Heading\nReal content here.\n\n\n\nMore."
    assert clean_llm_markdown(raw) == "Real content here.\n\nMore."


def test_clean_llm_markdown_keeps_normal_text_starting_with_here_word():
    assert clean_llm_markdown("Heresy is a topic.").startswith("Heresy")


def test_clamp_text_cuts_on_word_boundary():
    out = clamp_text("one two three four five six", 14)
    assert out.endswith("…") and len(out) <= 14 and " " not in out[-2:]


def test_sentences_splits_on_terminators():
    assert sentences("One is here. Two follows! Is three? Yes.") == ["One is here.", "Two follows!", "Is three?", "Yes."]


def test_coverage_counts_points_present():
    body = "Regular exercise improves cardiovascular health and mood."
    assert coverage(["exercise improves mood", "quantum computing basics"], body) == 0.5
    assert coverage([], body) == 1.0


def test_unique_ratio_detects_repetition():
    assert unique_ratio(["Same line here.", "same line here!", "Other thing."]) < 1.0
    assert unique_ratio(["a b", "c d"]) == 1.0


def test_clean_takeaways_removes_json_debris_seen_in_live_output():
    leaked = ["{", "keytakeaway1: Heart-Healthy Eating: Focus on a Mediterranean diet.",
              "keytakeaway2: Stick to a consistent sleep schedule.", "- Limit blue light before bed.", "}", "ok"]
    assert clean_takeaways(leaked) == [
        "Heart-Healthy Eating: Focus on a Mediterranean diet.",
        "Stick to a consistent sleep schedule.",
        "Limit blue light before bed.",
    ]


def test_clean_takeaways_dedupes_and_caps():
    assert len(clean_takeaways([f"Distinct useful point number {i}" for i in range(9)])) == 5
    assert clean_takeaways(["Same useful point here", "Same useful point here"]) == ["Same useful point here"]


def test_make_slug_is_safe_and_nonempty():
    assert make_slug("Hello, World! ../../etc") == "hello-world-etc"
    assert make_slug("!!!") == "post"
