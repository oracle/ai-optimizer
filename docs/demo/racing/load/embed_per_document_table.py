"""
Copyright (c) 2024, 2026, Oracle and/or its affiliates.
Licensed under the Universal Permissive License v1.0 as shown at http://oss.oracle.com/licenses/upl.

Stress-embed the racing corpus with N concurrent clients, where each
worker writes into its OWN vector store table (one table per document).

Every worker uses a unique Client header AND a unique alias derived
from the source filename. The server's alias -> table-name derivation
upper-cases and replaces non-word chars, so DRIVER_001 stays distinct
from DRIVER_002 etc.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _embed_common import (  # noqa: E402
    WorkerResult,
    build_argparser,
    cfg_from_args,
    execute,
    pick_files,
)


def _alias_for(filename: str, prefix: str) -> str:
    stem = re.sub(r"\W", "_", Path(filename).stem.upper())
    return f"{prefix}_{stem}"


def _description_for(path: Path) -> str | None:
    """Build a discovery-friendly description from the doc's header.

    The table-selection LLM only sees alias + description across 100 tables,
    so each one needs just enough identity signal to map a question like
    "I am Driver 1" to RACING_PERDOC_DRIVER_001. Including both the padded
    code and the human label covers both phrasings users tend to type.
    """
    try:
        head = path.read_text(encoding="utf-8", errors="replace").splitlines()[:30]
    except OSError:
        return None
    fields: dict[str, str] = {}
    for line in head:
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        if key in ("Driver label", "Driver code"):
            fields[key] = val.strip()
    label = fields.get("Driver label")
    code = fields.get("Driver code")
    if not (label and code):
        return None
    return f"{code} ({label}) Analysis"


def main() -> int:
    parser = build_argparser(__doc__)
    parser.add_argument(
        "--alias-prefix",
        default="RACING_PERDOC",
        help="Alias prefix; full alias is {prefix}_{FILENAME_STEM}",
    )
    args = parser.parse_args()
    cfg = cfg_from_args(args)

    files = pick_files(Path(args.corpus_dir), args.workers)
    results = [
        WorkerResult(
            worker_id=i,
            client_id=f"{cfg.client_prefix}{i:03d}",
            filename=files[i].name,
            alias=_alias_for(files[i].name, args.alias_prefix),
            description=_description_for(files[i]),
        )
        for i in range(args.workers)
    ]
    return execute(cfg, results, files)


if __name__ == "__main__":
    sys.exit(main())
