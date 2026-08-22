"""
Comprehensive verification of Modules 1-8 against real parsed data.
Run from cpi-ai-assistant project root:
    python verify_all_modules.py

Prints PASS/FAIL/WARN per module, with concrete evidence, not just
"looks fine". Read the WARN lines carefully - they flag things worth
a manual look even if not outright failures.
"""

import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.parser.iflow_parser import parse_package
from src.parser.mapping_resolver import resolve_mapping

ROOT = "data/raw_artifacts/CPI-NorthWind"

package_dirs = sorted(
    p.parent.parent for p in Path(ROOT).glob("*/META-INF/MANIFEST.MF")
)

print(f"Found {len(package_dirs)} packages to check.\n")

parsed = {}
failed = []
for pkg_dir in package_dirs:
    try:
        parsed[str(pkg_dir)] = parse_package(str(pkg_dir))
    except Exception as e:
        failed.append((pkg_dir, e))
        print(f"[FATAL] parse_package failed for {pkg_dir}:")
        import traceback
        traceback.print_exc()

if failed:
    print(f"\n{len(failed)} package(s) FAILED to parse entirely - see tracebacks above.\n")
else:
    print(f"All {len(package_dirs)} packages parsed without exception.\n")

print("=" * 70)
print("MODULE 1 - Universal property capture on messageFlows")
print("=" * 70)
total_flows = 0
flows_with_properties = 0
externalized_found = 0
literal_found = 0
for name, artifact in parsed.items():
    for mf in getattr(artifact, "message_flows", []):
        total_flows += 1
        props = mf.get("properties")
        if props:
            flows_with_properties += 1
            for k, v in props.items():
                if isinstance(v, dict) and "is_externalized" in v:
                    if v["is_externalized"]:
                        externalized_found += 1
                    else:
                        literal_found += 1
print(f"Total messageFlows checked: {total_flows}")
print(f"MessageFlows with a 'properties' dict populated: {flows_with_properties}")
print(f"Individual externalized ({{...}}) values found: {externalized_found}")
print(f"Individual literal values found: {literal_found}")
if flows_with_properties == 0:
    print("[FAIL] No messageFlow has a populated 'properties' dict at all.")
elif flows_with_properties < total_flows:
    print(f"[WARN] {total_flows - flows_with_properties} messageFlows have NO properties captured - inspect these by name.")
else:
    print("[PASS] Every messageFlow has a properties dict.")
print()

print("=" * 70)
print("MODULE 2 - Multi-process parsing + reconciliation")
print("=" * 70)
any_multi_process = False
reconciliation_ok = True
for name, artifact in parsed.items():
    processes = getattr(artifact, "processes", None)
    if not processes:
        continue
    if len(processes) > 1:
        any_multi_process = True
    total_across = sum(len(p["nodes"]) for p in processes)
    main_entries = [p for p in processes if p.get("classification") == "main"]
    if len(main_entries) != 1:
        print(f"[WARN] {name}: expected exactly 1 'main' process, found {len(main_entries)}")
        reconciliation_ok = False
    main_nodes = len(getattr(artifact, "nodes", []))
    main_process_nodes = len(main_entries[0]["nodes"]) if main_entries else -1
    if main_entries and main_nodes != main_process_nodes:
        print(f"[WARN] {name}: top-level nodes ({main_nodes}) != main process nodes ({main_process_nodes})")
        reconciliation_ok = False
if not any_multi_process:
    print("[WARN] No package showed more than 1 process - expected Data_Extractor_copy to have 13+.")
elif reconciliation_ok:
    print("[PASS] Multi-process packages found, main process reconciles with top-level nodes.")
print()

print("=" * 70)
print("MODULE 3 - Activity type interpreters (details field)")
print("=" * 70)
interesting_types = {
    "Enricher", "ProcessCallElement", "Splitter", "Multicast", "Gather",
    "Filter", "DBstorage", "StartErrorEvent", "ErrorEventSubProcessTemplate",
    "EndErrorEvent",
}
found_details_by_type = {}
for name, artifact in parsed.items():
    all_nodes = list(getattr(artifact, "nodes", []))
    for p in getattr(artifact, "processes", []) or []:
        all_nodes.extend(p.get("nodes", []))
    for n in all_nodes:
        t = n.get("type") or n.get("activity_type")
        if t in interesting_types and "details" in n:
            found_details_by_type.setdefault(t, 0)
            found_details_by_type[t] += 1
for t in sorted(interesting_types):
    count = found_details_by_type.get(t, 0)
    marker = "[PASS]" if count > 0 else "[WARN - not seen in this corpus or not extracted]"
    print(f"  {t}: {count} nodes with 'details' populated  {marker}")
print()

print("=" * 70)
print("MODULE 4 - XSD resolver")
print("=" * 70)
xsd_resolved = 0
xsd_unresolved = 0
for name, artifact in parsed.items():
    for fname, detail in getattr(artifact, "resolved_resources", {}).items():
        if fname.lower().endswith(".xsd"):
            if detail.get("resolved") is False or "no resolver registered" in str(detail.get("note", "")):
                xsd_unresolved += 1
                print(f"[FAIL] {name}: {fname} still shows 'no resolver registered'")
            else:
                xsd_resolved += 1
print(f"XSDs resolved: {xsd_resolved}, still unresolved: {xsd_unresolved}")
if xsd_unresolved == 0 and xsd_resolved > 0:
    print("[PASS] All encountered XSDs resolved.")
print()

print("=" * 70)
print("MODULE 5 - Groovy CPI API detection")
print("=" * 70)
groovy_with_apis = 0
groovy_total = 0
for name, artifact in parsed.items():
    for fname, detail in getattr(artifact, "resolved_resources", {}).items():
        if fname.lower().endswith(".groovy"):
            groovy_total += 1
            if detail.get("cpi_apis"):
                groovy_with_apis += 1
print(f"Groovy scripts checked: {groovy_total}, with cpi_apis populated: {groovy_with_apis}")
if groovy_total > 0 and groovy_with_apis == 0:
    print("[FAIL] No groovy script shows any detected cpi_apis.")
elif groovy_with_apis < groovy_total:
    print(f"[WARN] {groovy_total - groovy_with_apis} scripts show no cpi_apis - could be legitimately empty, verify a couple manually.")
else:
    print("[PASS] cpi_apis populated across all groovy scripts found.")
print()

print("=" * 70)
print("MODULE 6 - Mapping resolver (3-way format detection)")
print("=" * 70)
mmap_files = glob.glob(f"{ROOT}/**/*.mmap", recursive=True)
format_counts = {}
warning_files = []
raw_structure_total = 0
for f in mmap_files:
    r = resolve_mapping(f)
    fmt = r.get("format", "unknown")
    format_counts[fmt] = format_counts.get(fmt, 0) + 1
    if r.get("parse_warnings"):
        warning_files.append((f, r["parse_warnings"]))
    raw_structure_total += sum(1 for fm in r.get("field_mappings", []) if "raw_structure" in fm)
print(f"Total .mmap files: {len(mmap_files)}")
print(f"Format breakdown: {format_counts}")
print(f"Total fields with raw_structure populated (complex mappings): {raw_structure_total}")
if warning_files:
    print(f"[WARN] {len(warning_files)} files still produced parse_warnings:")
    for f, w in warning_files:
        print(f"   - {f}: {w}")
else:
    print("[PASS] Zero parse_warnings across all .mmap files.")
print()

print("=" * 70)
print("MODULE 7 - metainfo.prop developer_description")
print("=" * 70)
desc_found = 0
for name, artifact in parsed.items():
    if getattr(artifact, "developer_description", None):
        desc_found += 1
print(f"Packages with a developer_description captured: {desc_found} / {len(parsed)}")
print("(Not all packages will have one - this field is optional/best-effort by design.)")
print()

print("=" * 70)
print("MODULE 8 - subflow_links.json")
print("=" * 70)
links_path = Path("output/subflow_links.json")
if not links_path.exists():
    print("[FAIL] output/subflow_links.json does not exist.")
else:
    links = json.loads(links_path.read_text(encoding="utf-8"))
    print(f"Total links found: {len(links)}")
    for l in links:
        print(f"   {l['caller']} -> {l['callee']}  (address: {l['address']})")
    expected = {
        ("NorthWind_Customer_OData_Git", "Subflow_1_Northwind_Customer_Data"),
        ("Subflow_1_Northwind_Customer_Data", "Subflow_2_Northwind_Customer_Data"),
    }
    found_pairs = {(l["caller"], l["callee"]) for l in links}
    if expected.issubset(found_pairs):
        print("[PASS] Both known-correct NorthWind links are present.")
    else:
        missing = expected - found_pairs
        print(f"[FAIL] Missing expected link(s): {missing}")
print()

print("=" * 70)
print("DONE - review every WARN and FAIL line above before touching Neo4j.")
print("=" * 70)