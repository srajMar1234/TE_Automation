from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class RunContext:
    run_id: str
    base_dir: Path
    download_dir: Path
    output_dir: Path
    log_dir: Path
    started_at: datetime


@dataclass(frozen=True)
class ReportArtifact:
    source_report: str
    extracted_at: datetime
    payload: pd.DataFrame
    metadata: dict[str, Any]
