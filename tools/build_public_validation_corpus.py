"""Build the deterministic FINCO public validation corpus artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Direct ``python tools/...py`` execution places ``tools/`` rather than the
# repository root on sys.path.  Add the root explicitly so this utility behaves
# the same in local shells and GitHub Actions without requiring package install.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from finco_protocol.verification.public_corpus import (  # noqa: E402
    build_public_validation_corpus,
    verify_public_validation_corpus,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/finco-public-validation-corpus.json",
        help="JSON artifact path",
    )
    args = parser.parse_args()

    corpus = build_public_validation_corpus()
    if not verify_public_validation_corpus(corpus):
        raise SystemExit("FINCO_PUBLIC_VALIDATION_CORPUS_VERIFY_FAILED")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(corpus, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        "FINCO_PUBLIC_VALIDATION_CORPUS_PASS "
        f"cases={len(corpus['cases'])} sha256={corpus['corpusSha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
