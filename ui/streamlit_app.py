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
    with right:
        st.markdown("**Pipeline**  \nResearch → Plan → Write → Quality gates → Review → Publish")
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
            job = api("POST", "/blogs", json={"topic": topic, "length": length, "tone": tone, "audience": audience}).json()
            st.session_state.job_id = job["id"]
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
            status_box.info(f"**{job['status'].title()}** · {job['message'] or 'Waiting for a worker...'} · {job['elapsed_s']}s")
            log_box.code("\n".join(f"{e['stage']:9} {e['message']}" for e in job["events"][-8:]) or "queued", language="text")
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
