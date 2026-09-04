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
from src.agent.tools import list_all_iflows, get_graph_summary

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
        
        # Data freshness indicator
        try:
            summary = get_graph_summary()
            if "error" not in summary:
                iflow_count = summary.get("iflow_count", 0)
                step_count = summary.get("step_count", 0)
                st.caption(f"📊 Graph: {iflow_count} iFlows, {step_count} steps")
            else:
                st.caption("📊 Graph: Connection issue")
        except Exception as exc:
            st.caption(f"📊 Graph: Error loading data")
        
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

    # Example questions - only show when chat is empty (at start of conversation)
    if len(st.session_state.messages) == 0:
        st.markdown("### Example questions:")
        example_questions = [
            "Which iFlows call Subflow_1_Northwind_Customer_Data as a subflow?",
            "How many iFlows have error-handling subprocesses?",
            "Which mappings use complex transformation logic, not direct copies?",
            "Which iFlows combine complex mapping logic with zero error handling?",
            "What is the purpose of script1.groovy in Data_Extractor_copy?",
            "Trace the full call chain from the main NorthWind flow to its deepest subflow.",
        ]
        
        cols = st.columns(2)
        for i, question in enumerate(example_questions):
            col = cols[i % 2]
            with col:
                if st.button(question, key=f"example_q_{i}", use_container_width=True):
                    st.session_state.messages.append({"role": "user", "content": question})
                    with st.chat_message("user"):
                        st.markdown(question)

                    with st.chat_message("assistant"):
                        with st.spinner("Thinking..."):
                            answer = chat_turn(st.session_state.chat, question)
                        if contains_mermaid(answer):
                            render_mermaid(answer, key=f"diagram_new_{len(st.session_state.messages)}")
                        else:
                            st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                    st.rerun()

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
        st.rerun()


if __name__ == "__main__":
    render_chat()
