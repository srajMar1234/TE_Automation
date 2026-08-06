import pandas as pd


def validate_not_empty(df: pd.DataFrame, name: str) -> None:
    if df.empty:
        raise ValueError(f"{name} is empty")


def validate_required_columns(df: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{name} missing columns: {missing}")
