"""
CPI Integration Assistant — Streamlit UI
Wraps the existing Gemini chat agent (src/agent/chat.py) and tools 
(src/agent/tools.py) in a web chat interface, with Mermaid diagram rendering.
"""
import sys
import re
from pathlib import Path

# Add project root to sys.path so "src.*" imports resolve when run via `streamlit run`
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st
import streamlit.components.v1 as components

from src.agent.chat import create_chat, chat_turn
from src.agent.tools import list_all_iflows

def extract_mermaid(text: str) -> str:
    """Pull out just the Mermaid diagram content, stripping any code fences 
    or commentary the model added around it."""
    match = re.search(r"```(?:mermaid)?\s*\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    idx = text.find("flowchart")
    if idx == -1:
        idx = text.find("graph TD")
    return text[idx:].strip() if idx != -1 else text.strip()


def render_mermaid(diagram_text: str, key: str):
    """Render Mermaid syntax as an actual diagram using Mermaid.js via CDN."""
    html = f"""
    <div class="mermaid">
    {extract_mermaid(diagram_text)}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});
    </script>
    """
    components.html(html, height=600, scrolling=True)


def contains_mermaid(text: str) -> bool:
    return "flowchart" in text or "graph TD" in text


def render_chat() -> None:
    """Render the CPI Integration Assistant chat page."""
    st.set_page_config(page_title="CPI Integration Assistant", layout="wide")

    with st.sidebar:
        st.header("iFlows in scope")
        try:
            iflows = list_all_iflows()
            for iflow in iflows:
                if "error" not in iflow:
                    st.markdown(f"- **{iflow['artifact_id']}** (v{iflow.get('version', '?')})")
        except Exception as exc:
            st.error(f"Could not load iFlow list: {exc}")

        st.divider()
        if st.button("New conversation"):
            st.session_state.messages = []
            st.session_state.chat = create_chat()
            st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "chat" not in st.session_state:
        st.session_state.chat = create_chat()

    st.title("CPI Integration Assistant")
    st.caption("Ask questions about iFlows, resources, and systems in your CPI landscape.")

    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            if message["role"] == "assistant" and contains_mermaid(message["content"]):
                render_mermaid(message["content"], key=f"diagram_{index}")
            else:
                st.markdown(message["content"])

    user_input = st.chat_input("Ask about your CPI integration landscape...")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                answer = chat_turn(st.session_state.chat, user_input)
            if contains_mermaid(answer):
                render_mermaid(answer, key=f"diagram_new_{len(st.session_state.messages)}")
            else:
                st.markdown(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    render_chat()
