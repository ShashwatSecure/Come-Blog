import os

import requests
import streamlit as st

API_BASE = os.environ.get("COMEBLOG_API_BASE", "http://localhost:8000")

st.set_page_config(page_title="Come-Blog", page_icon="📝")
st.title("Come-Blog")
st.caption("A simple interactive blog writer powered by local Ollama.")

topic = st.text_input("Topic", placeholder="e.g. Why observability matters for small teams")
check = st.button("Check Ollama", disabled=not topic.strip())

if check:
    try:
        resp = requests.get(f"{API_BASE}/ollama/check", timeout=90)
        resp.raise_for_status()
        st.success(resp.json()["message"])
    except requests.RequestException as exc:
        st.error(f"Ollama check failed: {exc}")

if st.button("Get Topic Preview", disabled=not topic.strip()):
    try:
        resp = requests.post(f"{API_BASE}/preview", json={"topic": topic}, timeout=120)
        resp.raise_for_status()
        st.session_state.preview = resp.json()["preview"]
    except requests.RequestException as exc:
        st.error(f"Preview failed: {exc}")

if st.session_state.get("preview"):
    st.subheader("Topic preview")
    st.write(st.session_state.preview)
    st.write("Do you want a complete blog?")
    if st.button("Yes, generate the blog"):
        try:
            resp = requests.post(f"{API_BASE}/blogs", json={"topic": topic}, timeout=180)
            resp.raise_for_status()
            result = resp.json()
            st.subheader("Draft history")
            for attempt in result["attempts"]:
                st.markdown(f"#### Draft {attempt['iteration']}")
                st.markdown(attempt["draft"])
                st.caption(
                    f"Evaluator score: {attempt['score']:.2f} | Feedback: {attempt['feedback']}"
                )
            st.subheader("Final blog")
            st.markdown(result["markdown"])
            st.download_button(
                "Download .md",
                data=f"# {topic}\n\n{result['markdown']}\n",
                file_name=os.path.basename(result["output_path"]),
                mime="text/markdown",
            )
        except requests.RequestException as exc:
            st.error(f"Blog generation failed: {exc}")
