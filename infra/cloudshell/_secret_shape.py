"""Describe a secret's shape (length, format) from stdin without printing it."""
import re
import sys

label = sys.argv[1] if len(sys.argv) > 1 else "secret"
raw = sys.stdin.buffer.read()
t = raw.decode("utf-8", "replace").strip()
print(f"{label}: {len(raw)} bytes, {len(t)} chars after trim, "
      f"looks like a GitHub secret (40 hex)={bool(re.fullmatch(r'[0-9a-f]{40}', t))}, "
      f"contains escape codes={chr(27) in t}, contains spaces={any(c.isspace() for c in t)}")
