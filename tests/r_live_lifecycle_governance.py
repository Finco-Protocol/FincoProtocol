"""Current guard adapter; historical Radar/Model/Finance authorities stay immutable.

Only the separately approved two-blob PR #346 content can augment the original
answer. Every financial engine decision delegates unchanged to its old authority.
No test import hook, monkeypatch, scope-file permission or namespace grant.
"""
from pathlib import Path
from r_live_lifecycle_content_authority import reviewed_lifecycle_content_matches

REPO=Path(__file__).resolve().parents[1]


def approved_frozen_path(path: str) -> bool:
    from finance_integrity_governance import approved_frozen_path as historical
    return historical(path) or reviewed_lifecycle_content_matches(path,repo=REPO)


def model_v2_frozen_violations(changed: list[str] | None = None) -> list[str]:
    from model_v2_governance import model_v2_frozen_violations as historical
    return [path for path in historical(changed)
            if not reviewed_lifecycle_content_matches(path,repo=REPO)]


def reviewed_radar_authority_matches(path: str, *, repo=None, ref='HEAD') -> bool:
    from radar_authority_governance import reviewed_radar_authority_matches as historical
    target=repo if repo is not None else REPO
    return historical(path,repo=target,ref=ref) or reviewed_lifecycle_content_matches(path,repo=target,ref=ref)
