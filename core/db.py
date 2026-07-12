from __future__ import annotations

from functools import wraps
from typing import Callable, ParamSpec, TypeVar

from django.db import models, router, transaction


P = ParamSpec("P")
R = TypeVar("R")


def atomic_for_model(model: type[models.Model]) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Run a service transaction on the database selected for a model write."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with transaction.atomic(using=router.db_for_write(model)):
                return func(*args, **kwargs)

        return wrapper

    return decorator
