"""Extracted core serialization helpers; behavior retained."""
from __future__ import annotations
from backend.core import context as dependencies
from typing import Any
from pathlib import Path
import json
import numpy as np
import pandas as pd

def clean(
    value: Any,
):
    """Convert pandas/numpy values into JSON-safe Python values."""

    if isinstance(
        value,
        dict,
    ):

        return {
            key:
                clean(
                    item
                )

            for (
                key,
                item,
            ) in value.items()
        }


    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):

        return [
            clean(
                item
            )
            for item
            in value
        ]


    if isinstance(
        value,
        np.integer,
    ):

        return int(
            value
        )


    if isinstance(
        value,
        np.floating,
    ):

        if not np.isfinite(
            value
        ):
            return None

        return float(
            value
        )


    if isinstance(
        value,
        np.bool_,
    ):

        return bool(
            value
        )


    if (
        value is None
        or value is pd.NA
    ):

        return None


    if (
        isinstance(
            value,
            float,
        )
        and not np.isfinite(
            value
        )
    ):

        return None


    try:

        if pd.isna(
            value
        ):
            return None

    except (
        TypeError,
        ValueError,
    ):
        pass


    return value

def _read_json(
    path: Path,
) -> dict[str, Any]:

    if not path.exists():
        return {}


    try:

        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except (
        OSError,
        json.JSONDecodeError,
    ):

        return {}

def _csv_row_count(
    path: Path,
) -> int:

    if not path.exists():
        return 0


    try:

        return int(
            len(
                pd.read_csv(
                    path
                )
            )
        )

    except Exception:
        return 0
