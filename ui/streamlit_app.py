import os
import time

import requests
import streamlit as st

API_BASE = os.environ.get("COMEBLOG_API_BASE", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("COMEBLOG_API_KEY", "")
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}
STAGES = [("research", "Research"), ("plan", "Plan"), ("write", "Write"), ("assemble", "Quality gates"),
          ("review", "Review"), ("publish", "Publish")]

st.set_page_config(page_title="Come-Blog", page_icon="📝", layout="wide")


def api(method: str, path: str, **kwargs):
    response = requests.request(method, f"{API_BASE}{path}", headers=HEADERS, timeout=kwargs.pop("timeout", 30), **kwargs)
    response.raise_for_status()
    return response


def error_text(exc: requests.RequestException) -> str:
    detail = getattr(getattr(exc, "response", None), "text", "")
    return f"{exc} {detail[:200]}".strip()


def send_feedback(job_id: str, body: dict) -> None:
    try:
        api("POST", f"/jobs/{job_id}/feedback", json=body)
    except requests.RequestException as exc:
        st.error(f"Could not send your feedback: {error_text(exc)}")
        return
    st.rerun()


def _lines(text: str) -> list[str]:
    return [line.strip(" -•\t") for line in text.splitlines() if line.strip(" -•\t")]


def render_plan_review(job_id: str, plan: dict) -> None:
    st.subheader("🧑 Your turn: review the outline")
    st.caption("Nothing has been written yet. Edit headings, briefs and key points, drop sections, or approve as is.")
    with st.form(f"plan-{job_id}"):
        title = st.text_input("Title", plan["title"])
        subtitle = st.text_input("Subtitle", plan.get("subtitle", ""))
        sections = []
        for i, s in enumerate(plan["sections"]):
            with st.container(border=True):
                keep = st.checkbox("Keep this section", value=True, key=f"keep-{job_id}-{i}")
                heading = st.text_input("Heading", s["heading"], key=f"h-{job_id}-{i}")
                brief = st.text_input("Brief", s.get("brief", ""), key=f"b-{job_id}-{i}")
                points = st.text_area("Key points (one per line)", "\n".join(s.get("key_points", [])), key=f"k-{job_id}-{i}")
                if keep and heading.strip():
                    sections.append({"heading": heading.strip(), "brief": brief, "key_points": _lines(points)[:6]})
        extra = st.text_input("Add a section (optional heading)", key=f"new-{job_id}")
        if extra.strip():
            sections.append({"heading": extra.strip(), "brief": extra.strip(), "key_points": []})
        if st.form_submit_button("Approve outline and start writing", type="primary"):
            edited = {**plan, "title": title, "subtitle": subtitle, "sections": sections}
            send_feedback(job_id, {"action": "continue", "plan": edited if edited != plan else None})


def render_draft_review(job_id: str, p: dict) -> None:
    st.subheader(f"🧑 Your turn: draft {p['attempt']} of max {p['max_attempts']}")
    m1, m2, m3 = st.columns(3)
    m1.metric("Evaluator score", f"{p['llm_score']:.2f}" if p["llm_score"] is not None else "n/a")
    m2.metric("Quality gates", "passed" if p["passed"] else f"{len(p['failing_checks'])} failing")
    m3.metric("Words", f"{p['word_count']:,}")
    if p["llm_feedback"]:
        st.info(f"**Evaluator says:** {p['llm_feedback']}")
    for c in p["failing_checks"]:
        st.warning(f"{c['name']}: {c['detail']}")
    with st.expander("Read the draft", expanded=True):
        for s in p["sections"]:
            st.markdown(f"### {s['heading']}\n{s['body_md']}")
    with st.form(f"review-{job_id}-{p['attempt']}"):
        points = st.text_area(
            "Feedback for the next draft (one point per line). Keep what the evaluator got right, fix or delete what it "
            "got wrong, and add your own points.", "\n".join(p["suggested_points"]), height=160)
        headings = [s["heading"] for s in p["sections"]]
        targets = st.multiselect("Sections to rewrite", headings, default=[h for h in p["suggested_sections"] if h in headings])
        b1, b2 = st.columns(2)
        rewrite = b1.form_submit_button("Rewrite with this feedback", type="primary", disabled=not p["can_rewrite"])
        publish = b2.form_submit_button("Approve and publish")
        if not p["can_rewrite"]:
            st.caption("The rewrite limit is reached; this draft can only be published.")
        if rewrite:
            send_feedback(job_id, {"action": "rewrite", "feedback_points": _lines(points), "sections": targets})
        elif publish:
            send_feedback(job_id, {"action": "publish"})


def render_pending(job_id: str, pending: dict) -> None:
    if pending["kind"] == "plan":
        render_plan_review(job_id, pending["payload"]["plan"])
    else:
        render_draft_review(job_id, pending["payload"])


st.title("📝 Come-Blog")
st.caption("Researched, written, reviewed and illustrated by local models. Every claim links to a source.")
create_tab, library_tab = st.tabs(["Create", "Library"])

with create_tab:
    left, right = st.columns([3, 2])
    with left:
        topic = st.text_input("Topic", placeholder="e.g. Why observability matters for small teams", max_chars=300)
        c1, c2, c3 = st.columns(3)
        length = c1.selectbox("Length", ["short", "medium", "long"], index=1, help="short ≈ 3 sections, medium ≈ 4, long ≈ 6")
        tone = c2.selectbox("Tone", ["conversational", "professional", "playful", "authoritative"])
        audience = c3.text_input("Audience", "general readers", max_chars=80)
        interactive = st.toggle("Review each step myself (human in the loop)", value=True,
                                help="Pause after the outline and after every evaluation so you can steer the next draft.")
    with right:
        st.markdown("**Pipeline**  \nResearch → Plan → 🧑 You → Write → Quality gates → Review → 🧑 You → Publish")
        if st.button("Check Ollama"):
            try:
                st.success(api("GET", "/ollama/check", timeout=120).json()["message"])
            except requests.RequestException as exc:
                st.error(f"Ollama check failed: {error_text(exc)}")

    ready = len(topic.strip()) >= 3
    p1, p2 = st.columns(2)
    if p1.button("Preview research", disabled=not ready):
        with st.spinner("Searching Wikipedia, Commons and the web..."):
            try:
                st.session_state.preview = api("POST", "/preview", json={"topic": topic}, timeout=60).json()
            except requests.RequestException as exc:
                st.error(f"Preview failed: {error_text(exc)}")
    preview = st.session_state.get("preview")
    if preview:
        with st.expander(f"Research preview: {len(preview['sources'])} sources, {preview['images']} images", expanded=True):
            st.write(preview["summary"] or "No overview found; the model will rely on general knowledge.")
            for s in preview["sources"]:
                st.markdown(f"{s['id']}. [{s['title']}]({s['url']}) · {s['domain']}")

    if p2.button("Generate blog", type="primary", disabled=not ready):
        try:
            job = api("POST", "/blogs", json={"topic": topic, "length": length, "tone": tone, "audience": audience,
                                               "interactive": interactive}).json()
            st.session_state.job_id = job["id"]
            st.session_state.pop("last_slug", None)
        except requests.RequestException as exc:
            st.error(f"Could not start generation: {error_text(exc)}")

    job_id = st.session_state.get("job_id")
    if job_id:
        bar, status_box, log_box = st.progress(0.0), st.empty(), st.empty()
        while True:
            try:
                job = api("GET", f"/jobs/{job_id}").json()
            except requests.RequestException as exc:
                st.error(f"Lost contact with the API: {error_text(exc)}")
                break
            bar.progress(job["progress"])
            state = job["status"].replace("_", " ").title()
            status_box.info(f"**{state}** · {job['message'] or 'Waiting for a worker...'} · {job['elapsed_s']}s")
            log_box.code("\n".join(f"{e['stage']:9} {e['message']}" for e in job["events"][-12:]) or "queued", language="text")
            if job["status"] == "awaiting_input":
                render_pending(job_id, job["pending"])
                break
            if job["status"] == "done":
                st.session_state.last_slug = job["slug"]
                st.session_state.pop("job_id")
                st.success("Published!")
                break
            if job["status"] == "failed":
                st.session_state.pop("job_id")
                st.error(f"Generation failed: {job['error']}")
                break
            time.sleep(1.5)

    slug = st.session_state.get("last_slug")
    if slug:
        try:
            post = api("GET", f"/posts/{slug}").json()
            q = post["quality"]
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Words", f"{post['word_count']:,}")
            m2.metric("Sources", len(post["sources"]))
            m3.metric("Images", len(post["images"]))
            m4.metric("Checks", f"{q['checks_passed']}/{q['checks_total']}")
            m5.metric("Reviewer", f"{q['llm_score']:.2f}" if q["llm_score"] is not None else "n/a")
            if post["status"] == "needs_review":
                st.warning("This post did not meet the quality bar after the allowed rewrites. Review it before sharing.")
            st.link_button("Open the published page", f"{API_BASE}/site/posts/{slug}/index.html")
            st.download_button("Download Markdown", api("GET", f"/posts/{slug}/markdown").content,
                               file_name=f"{slug}.md", mime="text/markdown")
            with st.expander("Writing passes"):
                for a in post["attempts"]:
                    st.write(f"Pass {a['attempt']}: {a['word_count']} words · checks {a['checks_passed']}/{a['checks_total']} · "
                             f"score {a['llm_score'] if a['llm_score'] is not None else 'n/a'} · {a['feedback']}")
                    if a.get("human_feedback"):
                        st.caption("Your feedback for the next pass: " + " · ".join(a["human_feedback"]))
            st.divider()
            st.markdown(requests.get(f"{API_BASE}/posts/{slug}/markdown", headers=HEADERS, timeout=30).text
                        .replace("(image-", f"({API_BASE}/site/posts/{slug}/image-"))
        except requests.RequestException as exc:
            st.error(f"Could not load the post: {error_text(exc)}")

with library_tab:
    try:
        data = api("GET", "/posts").json()
        s = data["stats"]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Posts", s["posts"]); k2.metric("Words", f"{s['words']:,}")
        k3.metric("Images", s["images"]); k4.metric("Needs review", s["needs_review"])
        st.link_button("Open the blog", f"{API_BASE}/site/index.html")
        for p in data["posts"]:
            with st.container(border=True):
                a, b = st.columns([5, 1])
                a.markdown(f"**[{p['title']}]({API_BASE}{p['url']})**  \n{p['excerpt']}  \n"
                           f"{p['reading_minutes']} min · {p['sources']} sources · {p['images']} images"
                           + (" · ⚠️ needs review" if p["status"] == "needs_review" else ""))
                if b.button("Delete", key=f"del-{p['slug']}"):
                    api("DELETE", f"/posts/{p['slug']}")
                    st.rerun()
    except requests.RequestException as exc:
        st.error(f"Could not load the library: {error_text(exc)}")
