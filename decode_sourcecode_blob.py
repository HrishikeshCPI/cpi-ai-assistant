import re
import base64
import zipfile
import io
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "data/raw_artifacts/CPI-NorthWind/com.sap.scenarios.c4c2s4.documentflowquery.sync/src/main/resources/mapping/C4C_S4_DocumentFlowRequest.mmap"

text = open(path, encoding="utf-8").read()

# Find the SourceCode blob specifically
match = re.search(r"<tr:SourceCode>.*?<tr:blob[^>]*>!zip!([A-Za-z0-9+/=]+)</tr:blob>.*?</tr:SourceCode>", text, re.DOTALL)
if not match:
    print("Could not find a SourceCode blob in this file.")
    sys.exit(1)

b64_data = match.group(1)
raw_bytes = base64.b64decode(b64_data)

def recursive_unwrap(content, depth=0, max_depth=10):
    indent = "  " * depth
    print(f"{indent}[depth {depth}] {len(content)} bytes, first 16 bytes hex: {content[:16].hex()}")

    if depth >= max_depth:
        print(f"{indent}Max depth reached, stopping.")
        return content

    # Try treating it as a zip file first
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            print(f"{indent}-> This is a zip. Inner files: {names}")
            if len(names) == 1:
                inner_content = zf.read(names[0])
                return recursive_unwrap(inner_content, depth + 1, max_depth)
            else:
                # Multiple files - print each, stop recursing automatically
                for n in names:
                    c = zf.read(n)
                    print(f"{indent}  --- {n} ({len(c)} bytes) ---")
                    try:
                        print(c.decode("utf-8")[:2000])
                    except UnicodeDecodeError:
                        print(f"{indent}  (binary, hex head: {c[:16].hex()})")
                return content
    except zipfile.BadZipFile:
        pass

    # Not a zip - try to decode as text directly
    try:
        text = content.decode("utf-8")
        print(f"{indent}-> Decoded as UTF-8 text ({len(text)} chars):")
        print(text[:3000])
        return content
    except UnicodeDecodeError:
        pass

    # Try zlib/deflate as last resort
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 16):
        try:
            decompressed = zlib.decompress(content, wbits)
            print(f"{indent}-> Decompressed via zlib (wbits={wbits})")
            return recursive_unwrap(decompressed, depth + 1, max_depth)
        except Exception:
            continue

    print(f"{indent}-> Could not unwrap further. Raw hex head: {content[:32].hex()}")
    return content

import zlib
with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
    print("Files inside SourceCode zip:", zf.namelist())
    for name in zf.namelist():
        content = zf.read(name)
        print(f"\n=== Unwrapping {name} ===")
        recursive_unwrap(content)