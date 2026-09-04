"""Technical Specification preview page for CPI iFlows."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.agent.tools import list_all_iflows
from src.docgen.ts_document import build_ts_content
from src.docgen.word_export import generate_ts_docx
from src.ui.app import render_mermaid


def _group_iflows_by_family(iflows: list[dict]) -> dict[str, list[dict]]:
    """Group iFlows by family based on artifact_id patterns."""
    groups = {
        "S4/C4C Replication Scenarios": [],
        "Complaint Handling": [],
        "Agricultural / Master Data": [],
        "NorthWind Demo": [],
    }

    # Hardcoded IDs for Agricultural / Master Data group
    agricultural_ids = {
        "Create_or_Update_Address_In_Complaint_Handling",
        "Create_or_Update_DefectCode_Master_Data_In_Complain",
        "Create_or_Update_Subject_Code_Group_in_SAP_Complain",
        "Delete_Address_In_Complaint_Handling",
        "Delete_Defect_Code_Master_Data_In_Complaint_Handlin",
        "Generate_Password_Credential_Token_for_Farmer_Porta",
    }

    for iflow in iflows:
        artifact_id = iflow.get("artifact_id", "")
        
        if artifact_id.startswith("com.sap.scenarios"):
            groups["S4/C4C Replication Scenarios"].append(iflow)
        elif "Complaint" in artifact_id or "complaint" in artifact_id.lower():
            groups["Complaint Handling"].append(iflow)
        elif artifact_id in agricultural_ids:
            groups["Agricultural / Master Data"].append(iflow)
        elif artifact_id.startswith("NorthWind") or artifact_id.startswith("Subflow"):
            groups["NorthWind Demo"].append(iflow)
        else:
            # Default to NorthWind Demo if doesn't match other patterns
            groups["NorthWind Demo"].append(iflow)

    # Sort each group alphabetically by artifact_id
    for group_name in groups:
        groups[group_name] = sorted(groups[group_name], key=lambda x: x.get("artifact_id", ""))

    return groups


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

    # Group iFlows by family for two-step selectbox (Phase 1 enrichment #6)
    groups = _group_iflows_by_family(iflows)
    group_names = list(groups.keys())
    
    col1, col2 = st.columns(2)
    with col1:
        selected_group = st.selectbox("Family", group_names)
    with col2:
        iflows_in_group = [iflow["artifact_id"] for iflow in groups[selected_group]]
        artifact_id = st.selectbox("iFlow", iflows_in_group)

    with st.spinner("Building technical specification preview..."):
        content = build_ts_content(artifact_id)

    st.title(f"{content['artifact_id']} (v{content['version']})")
    
    # Phase 1 enrichment #1: Developer description (italicized, conditional)
    developer_description = content.get("developer_description", "")
    if developer_description:
        st.caption(f"*Developer note: {developer_description}*")

    st.subheader("Scope")
    st.write(content["scope_summary"])

    # Phase 1 enrichment #3: Subflow Relationships section (new, conditional)
    subflows = content.get("subflows", {})
    calls = subflows.get("calls", [])
    called_by = subflows.get("called_by", [])
    if calls or called_by:
        st.subheader("Subflow Relationships")
        col1, col2 = st.columns(2)
        with col1:
            if calls:
                st.markdown("**Calls:**")
                for call in calls:
                    target_name = call.get("artifact_id") or call.get("callee") or "Unknown"
                    address = call.get("address") or ""
                    if address:
                        st.markdown(f"- {target_name} via {address}")
                    else:
                        st.markdown(f"- {target_name}")
        with col2:
            if called_by:
                st.markdown("**Called by:**")
                for caller in called_by:
                    source_name = caller.get("artifact_id") or caller.get("caller") or "Unknown"
                    address = caller.get("address") or ""
                    if address:
                        st.markdown(f"- {source_name} via {address}")
                    else:
                        st.markdown(f"- {source_name}")

    st.subheader("Process Flow")
    render_mermaid(content["diagram"], key=f"ts_diagram_{artifact_id}")

    # Phase 1 enrichment #2: Process Structure section (new, conditional)
    processes = content.get("processes", [])
    non_main_processes = [p for p in processes if p.get("classification") != "main"]
    if non_main_processes:
        st.subheader("Process Structure")
        for process in non_main_processes:
            process_id = process.get("id", "")
            classification = process.get("classification", "")
            step_count = process.get("step_count", 0)
            
            label = f"{classification.replace('_', ' ').title()}: {process_id} ({step_count} steps)"
            
            with st.expander(label):
                # Show error handling trigger info if available
                error_info = content.get("error_details_by_process", {}).get(process_id)
                if error_info:
                    trigger_types = error_info.get("trigger_types", [])
                    terminal_steps = error_info.get("terminal_steps", [])
                    
                    if trigger_types:
                        st.markdown(f"**Trigger types:** {', '.join(trigger_types)}")
                    if terminal_steps:
                        st.markdown(f"**Terminal steps:** {', '.join(terminal_steps)}")

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

    # NEW Phase 2 addition: Groovy Script Summaries - display cached summary data
    groovy_scripts = {}
    resources = content.get("resources", [])
    for resource in resources:
        if resource.get("kind") == "groovy":
            filename = resource.get("filename", "")
            groovy_scripts[filename] = resource
    
    if groovy_scripts:
        st.subheader("Groovy Script Summaries")
        for filename, resource in groovy_scripts.items():
            resolved = resource.get("resolved", False)
            with st.expander(f"📜 {filename}"):
                if resolved:
                    purpose = resource.get("purpose", "")
                    complexity = resource.get("complexity", "")
                    business_note = resource.get("business_note", "")
                    
                    if purpose:
                        st.markdown(f"**Purpose:** {purpose}")
                    if complexity:
                        st.markdown(f"**Complexity:** {complexity}")
                    if business_note:
                        st.markdown(f"**Business Note:** {business_note}")
                    if not (purpose or complexity or business_note):
                        st.caption("No summary details available for this script.")
                else:
                    st.caption("⚠️ No summary generated yet for this script.")

    if content["field_mappings"]:
        st.subheader("Field Mappings")
        
        # Phase 1 enrichment #5: Complex mapping annotation note (conditional)
        has_complex = any(r.get("has_complex_transformations") for r in resources if r.get("kind") == "mapping")
        if has_complex:
            st.info("**Note:** This mapping contains non-trivial transformation logic beyond direct field copies.")
        
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
    # Phase 1 enrichment #4: Security/Adapter property column on Systems table
    systems_data = []
    for system in content["systems"]:
        if "error" in system:
            continue
        externalized = system.get("externalized_count") or 0
        literal = system.get("literal_count") or 0
        systems_data.append({
            "System": system.get("system_name", ""),
            "Direction": system.get("direction", ""),
            "Protocol": system.get("component_type", ""),
            "Address": system.get("address", ""),
            "Externalized / Literal Properties": f"{externalized} / {literal}",
        })
    
    st.dataframe(
        systems_data,
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
