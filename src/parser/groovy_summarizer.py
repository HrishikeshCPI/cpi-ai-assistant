from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


_CPI_API_PATTERNS = (
    "message.getProperty",
    "message.setProperty",
    "message.getBody",
    "message.setBody",
    "message.getHeaders",
    "messageLogFactory.getMessageLog",
    "messageLog.addAttachmentAsString",
)

_SUMMARY_KEYS = ("purpose", "reads", "writes", "side_effects", "complexity", "business_note")


def _scan_cpi_apis(content: str) -> list[dict[str, str | None]]:
    """Return deterministic CPI API usage, with a literal first argument when present."""
    matches: list[dict[str, str | None]] = []
    for api_name in _CPI_API_PATTERNS:
        pattern = re.escape(api_name) + r"\s*\(\s*(?:([\"'])(.*?)\1)?"
        for match in re.finditer(pattern, content, flags=re.DOTALL):
            matches.append({"api_name": api_name, "literal_argument": match.group(2)})
    return matches


def _cache_dir() -> Path:
    cache_dir = Path("output/.groovy_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _summary_prompt(filename: str, content: str) -> str:
    return f"""Analyze this SAP CPI Groovy script. Return only a JSON object with exactly these keys:
- purpose: concise plain-language sentence
- reads: list of message bodies, headers, properties, or other inputs read
- writes: list of bodies, headers, properties, logs, or other outputs written
- side_effects: list of external/logging effects, or [\"none\"]
- complexity: one of \"trivial\", \"moderate\", or \"business-logic\"
- business_note: concise business-rule explanation, or null

Do not invent behavior. Base every statement on the source.

Filename: {filename}
Source:
```groovy
{content}
```"""


def _parse_summary(response_text: str) -> dict[str, Any]:
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\\s*|\\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        summary = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gemini returned invalid Groovy-summary JSON") from exc
    if not isinstance(summary, dict) or set(summary) != set(_SUMMARY_KEYS):
        raise RuntimeError("Gemini returned a Groovy summary with an unexpected schema")
    if summary["complexity"] not in {"trivial", "moderate", "business-logic"}:
        raise RuntimeError("Gemini returned an invalid Groovy complexity value")
    for key in ("reads", "writes", "side_effects"):
        if not isinstance(summary[key], list) or not all(isinstance(value, str) for value in summary[key]):
            raise RuntimeError(f"Gemini returned an invalid {key} value")
    if not isinstance(summary["purpose"], str) or not (
        isinstance(summary["business_note"], str) or summary["business_note"] is None
    ):
        raise RuntimeError("Gemini returned invalid Groovy summary text")
    return summary


def _gemini_client() -> Any:
    """Create an untooled Gemini client for structured batch summarization."""
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in .env")
    from google import genai
    return genai.Client(api_key=api_key)


def generate_groovy_summary(
    groovy_path: str | Path,
    *,
    client: Any | None = None,
    cache_dir: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Generate and cache a structured Gemini summary for one Groovy script."""
    path = Path(groovy_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_bytes().decode("utf-8", errors="replace")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    target_dir = cache_dir or _cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    cache_path = target_dir / f"{content_hash}.json"
    if cache_path.exists() and not overwrite:
        return cache_path

    if client is None:
        client = _gemini_client()
    from google.genai import types
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=_summary_prompt(path.name, content),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    summary = _parse_summary(response.text or "")
    cache_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return cache_path


def generate_all_groovy_summaries(
    root_dir: str | Path = "data/raw_artifacts/CPI-NorthWind",
    *,
    client: Any | None = None,
    overwrite: bool = False,
) -> dict[str, int]:
    """Generate hash-keyed summaries for every Groovy script below ``root_dir``."""
    paths = sorted(Path(root_dir).rglob("*.groovy"))
    generated = skipped = 0
    seen_hashes: set[str] = set()
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_bytes().decode("utf-8", errors="replace")
        # Match resolve_groovy(), which hashes decoded text rather than raw bytes.
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            skipped += 1
            continue
        seen_hashes.add(content_hash)
        cache_path = _cache_dir() / f"{content_hash}.json"
        if cache_path.exists() and not overwrite:
            skipped += 1
            continue
        generate_groovy_summary(path, client=client, overwrite=overwrite)
        generated += 1
    return {"scripts": len(paths), "generated": generated, "skipped": skipped}


def resolve_groovy(groovy_path: str) -> dict[str, Any]:
    path = Path(groovy_path)
    _cache_dir()

    if not path.exists():
        return {"resolved": False, "note": "Groovy file not found", "filename": path.name}

    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = path.read_bytes().decode("utf-8", errors="replace")

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    cpi_apis = _scan_cpi_apis(content)
    cache_path = _cache_dir() / f"{content_hash}.json"
    expected_cache_path = str(Path("output/.groovy_cache") / f"{content_hash}.json")

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                cached["resolved"] = True
                cached["source"] = "cache"
                cached["cpi_apis"] = cpi_apis
                return cached
        except json.JSONDecodeError:
            pass

    return {
        "resolved": False,
        "note": "no cached summary found - generate one manually and save to output/.groovy_cache/<hash>.json",
        "filename": path.name,
        "expected_cache_path": expected_cache_path,
        "hash": content_hash,
        "cpi_apis": cpi_apis,
    }


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--all":
        root = sys.argv[2] if len(sys.argv) > 2 else "data/raw_artifacts/CPI-NorthWind"
        print(json.dumps(generate_all_groovy_summaries(root), indent=2))
        raise SystemExit(0)
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python -m src.parser.groovy_summarizer [--all [root_dir] | <groovy_file>]")

    result = resolve_groovy(sys.argv[1])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result.get("resolved"):
        if "hash" in result:
            print(f"Hash: {result['hash']}")
        if "expected_cache_path" in result:
            print(f"Expected cache path: {result['expected_cache_path']}")
