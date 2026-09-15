"""Run metadata structure for FINCO Protocol audit trail."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid

@dataclass
class RunMetadata:
    """Metadata for a single model run."""
    run_id: str
    timestamp: str
    model_version: str
    scenario: str
    project_type: str
    warnings: list[str] = field(default_factory=list)
    notes: str = ""
    git_sha: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "model_version": self.model_version,
            "scenario": self.scenario,
            "project_type": self.project_type,
            "warnings": self.warnings,
            "notes": self.notes,
            "git_sha": self.git_sha,
        }


def create_run_metadata(
    project_type: str,
    scenario: str = "Base",
    notes: str = "",
    warnings: list[str] = None,
) -> RunMetadata:
    """Create a new RunMetadata instance for a model run.
    
    Args:
        project_type: Solar | Wind | BESS | etc.
        scenario: Base | Downside | Upside
        notes: optional free-text notes
        warnings: optional list of warning codes from warn_model_unrealistic()
        
    Returns:
        RunMetadata instance
    """
    import subprocess
    
    git_sha = ""
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=None,
            text=True,
        ).strip()
    except Exception:
        git_sha = "unknown"
    
    return RunMetadata(
        run_id=f"run-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        model_version="industry-engine-refactor",
        scenario=scenario,
        project_type=project_type,
        warnings=warnings or [],
        notes=notes,
        git_sha=git_sha,
    )