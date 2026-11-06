"""The drift gate (#327): every generated file is byte-identical to its export.

The files listed in GENERATED.json are generated from the platform by its
export tool. An edit here, however correct, is the drift this repository
exists to prevent: a pack would pass its gate here and score differently at
the venue. Bytes are compared, never lines, so a changed line ending fails too.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HASHES = json.loads((ROOT / "GENERATED.json").read_text(encoding="utf-8"))["files"]


def test_every_generated_file_matches_its_export():
    drifted = []
    for path, expected in sorted(HASHES.items()):
        target = ROOT / path
        if not target.is_file():
            drifted.append(f"{path} (missing)")
        elif hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            drifted.append(path)
    assert not drifted, (
        "generated files differ from their export: " + ", ".join(drifted)
        + ". Do not edit generated files here. Change them upstream, or open an "
        "issue with a scenario pack that shows the problem."
    )
