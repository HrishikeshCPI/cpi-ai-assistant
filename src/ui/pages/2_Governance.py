"""Streamlit multipage entry point for Governance dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import streamlit as st

from src.agent.tools import (
    find_complex_mappings,
    find_complex_mappings_without_error_handling,
    get_all_subflow_links,
    get_error_handling_coverage,
)
from src.ui.app import render_mermaid


def render_governance_page() -> None:
    """Render the landscape governance overview."""
    st.title("Governance Dashboard")

    coverage = get_error_handling_coverage()
    if "error" in coverage:
        st.error(f"Could not load governance coverage: {coverage['error']}")
        return

    total_iflows = coverage.get("total_iflows_checked", 0)
    with_error = coverage.get("iflows_with_error_handling", [])
    no_error = coverage.get("iflows_without_error_handling", [])

    st.metric(
        "Error-handling coverage",
        f"{len(with_error)} of {total_iflows} iFlows have error handling",
    )

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Has error handling")
        if with_error:
            for entry in with_error:
                st.markdown(
                    f"- **{entry['artifact_id']}** ({entry.get('error_process_count', 0)} error process(es))"
                )
        else:
            st.caption("None")

    with col2:
        st.subheader("No error handling")
        if no_error:
            for artifact_id in no_error:
                st.markdown(f"- {artifact_id}")
        else:
            st.caption("None")

    st.markdown("---")

    complex = find_complex_mappings()
    if "error" in complex:
        st.error(f"Could not load complex-mapping data: {complex['error']}")
        return

    mappings = complex.get("complex_mappings", [])
    st.metric(
        "Complex mappings",
        f"{len(mappings)} mappings with complex transformation logic",
    )
    if mappings:
        for mapping in mappings:
            st.markdown(f"- **{mapping['artifact_id']}** — {mapping['filename']}")
    else:
        st.info("No complex mappings found.")

    st.markdown("---")

    findings = find_complex_mappings_without_error_handling()
    if "error" in findings:
        st.error(f"Could not compute governance finding: {findings['error']}")
    else:
        count = findings.get("count", 0)
        items = findings.get("complex_mapping_iflows_without_error_handling", [])
        with st.container():
            st.warning(
                f"**{count} iFlows combine complex mapping logic with zero error handling: "
                f"{', '.join(items) if items else 'None'}**"
            )

    st.markdown("---")

    subflow_links = get_all_subflow_links()
    if "error" in subflow_links:
        st.error(f"Could not load subflow link data: {subflow_links['error']}")
        return

    count = subflow_links.get("count", 0)
    st.subheader(f"{count} subflow relationships currently defined")
    links = subflow_links.get("links", [])
    if links:
        mermaid = ["graph TD"]
        for link in links:
            mermaid.append(f"    {link['caller']} -->|{link['address']}| {link['callee']}")
        render_mermaid("\n".join(mermaid), key="governance_subflow_graph")
    else:
        st.info("No subflow relationships are defined in the graph.")


if __name__ == "__main__":
    render_governance_page()
