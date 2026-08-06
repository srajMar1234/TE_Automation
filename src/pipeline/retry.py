import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    delay_seconds: float = 2.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
) -> T:
    errors: list[Exception] = []
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            errors.append(exc)
            if attempt == attempts:
                raise RuntimeError(f"Operation failed after {attempts} attempts") from exc
            time.sleep(delay_seconds * attempt)
    raise RuntimeError("Retry failed unexpectedly", errors[-1] if errors else None)
