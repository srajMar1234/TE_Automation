from datetime import datetime

import pandas as pd

from src.pipeline.contracts import ReportArtifact


def normalize_artifact(artifact: ReportArtifact, run_id: str) -> pd.DataFrame:
    df = artifact.payload.copy()
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]
    df["source_report"] = artifact.source_report
    df["run_id"] = run_id
    df["extracted_at"] = artifact.extracted_at.isoformat()
    df["normalized_at"] = datetime.utcnow().isoformat()
    return df
