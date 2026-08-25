"""Technical Specification preview page for CPI iFlows."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.agent.tools import list_all_iflows
from src.docgen.ts_document import build_ts_content
from src.docgen.word_export import generate_ts_docx
from src.ui.app import render_mermaid


def render_documentation_page() -> None:
    """Render a Technical Specification preview for a selected iFlow."""
    st.title("Technical Specification")
    try:
        iflows = [iflow for iflow in list_all_iflows() if "error" not in iflow]
    except Exception as exc:
        st.error(f"Could not load iFlows: {exc}")
        return
    if not iflows:
        st.info("No iFlows are available in the graph.")
        return

    artifact_id = st.selectbox("Choose an iFlow", [iflow["artifact_id"] for iflow in iflows])
    with st.spinner("Building technical specification preview..."):
        content = build_ts_content(artifact_id)

    st.title(f"{content['artifact_id']} (v{content['version']})")
    st.subheader("Scope")
    st.write(content["scope_summary"])

    st.subheader("Process Flow")
    render_mermaid(content["diagram"], key=f"ts_diagram_{artifact_id}")

    st.subheader("Process Steps")
    st.dataframe(
        [
            {
                "Name": step.get("name", ""),
                "Type": step.get("activity_type") or step.get("bpmn_type", ""),
                "Resources used": ", ".join(step.get("resources_used", [])),
            }
            for step in content["steps"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    if content["field_mappings"]:
        st.subheader("Field Mappings")
        st.dataframe(
            [
                {
                    "Source": mapping.get("source"),
                    "Target": mapping.get("target"),
                    "Function": mapping.get("function"),
                }
                for mapping in content["field_mappings"]
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.subheader("Systems & Endpoints")
    st.dataframe(
        [
            {
                "System": system.get("system_name", ""),
                "Direction": system.get("direction", ""),
                "Protocol": system.get("component_type", ""),
                "Address": system.get("address", ""),
            }
            for system in content["systems"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Externalized Parameters")
    for category, parameters in content["parameters"].items():
        st.markdown(f"#### {category}")
        st.dataframe(parameters, use_container_width=True, hide_index=True)

    if st.button("Generate Word document"):
        try:
            docx_path = generate_ts_docx(artifact_id)
            st.download_button(
                "Download as Word",
                data=Path(docx_path).read_bytes(),
                file_name=Path(docx_path).name,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        except Exception as exc:
            st.error(f"Could not generate Word document: {exc}")
