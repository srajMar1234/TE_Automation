from pathlib import Path

from src.pipeline.runner import run_pipeline


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    output = run_pipeline(root)
    print(f"Pipeline completed. Output: {output}")
