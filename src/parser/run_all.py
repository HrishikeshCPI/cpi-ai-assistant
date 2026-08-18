from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parser.iflow_parser import parse_package


def _find_package_dirs(root_dir: Path) -> list[Path]:
    if not root_dir.exists() or not root_dir.is_dir():
        return []

    package_dirs: list[Path] = []
    for child in sorted(root_dir.iterdir()):
        if child.is_dir() and (child / "META-INF" / "MANIFEST.MF").exists():
            package_dirs.append(child)
    return package_dirs


def _print_summary(rows: list[dict[str, object]]) -> None:
    headers = ["package", "artifact_id", "nodes", "edges", "warnings", "status"]
    widths = {header: len(header) for header in headers}

    for row in rows:
        for header in headers:
            value = str(row.get(header, ""))
            widths[header] = max(widths[header], len(value))

    line = "  ".join(header.ljust(widths[header]) for header in headers)
    print(line)
    print("  ".join("-" * widths[header] for header in headers))

    for row in rows:
        print("  ".join(str(row.get(header, "")).ljust(widths[header]) for header in headers))


def main() -> None:
    root_arg = sys.argv[1] if len(sys.argv) > 1 else "data/raw_artifacts/CPI-NorthWind"
    root_dir = Path(root_arg)

    package_dirs = _find_package_dirs(root_dir)
    summary_rows: list[dict[str, object]] = []

    if not package_dirs:
        print(f"No package folders found under: {root_dir}")
        return

    for package_dir in package_dirs:
        package_name = package_dir.name
        try:
            iflw_dir = package_dir / "src" / "main" / "resources" / "scenarioflows" / "integrationflow"
            iflw_files = sorted(iflw_dir.glob("*.iflw")) if iflw_dir.exists() else []
            if len(iflw_files) > 1:
                print(f"Warning: {package_name} has {len(iflw_files)} .iflw files under {iflw_dir}")

            artifact = parse_package(str(package_dir))
            output_dir = Path("output")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{artifact.artifact_id}.json"
            output_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")

            summary_rows.append(
                {
                    "package": package_name,
                    "artifact_id": artifact.artifact_id,
                    "nodes": len(artifact.nodes),
                    "edges": len(artifact.edges),
                    "warnings": len(artifact.parse_warnings),
                    "status": "OK",
                }
            )
        except Exception as exc:
            print(f"ERROR: {package_name} - {exc}")
            summary_rows.append(
                {
                    "package": package_name,
                    "artifact_id": "",
                    "nodes": 0,
                    "edges": 0,
                    "warnings": 0,
                    "status": "FAILED",
                }
            )

    _print_summary(summary_rows)


if __name__ == "__main__":
    main()
