import traceback

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def render_chart(df: pd.DataFrame, code: str) -> tuple:
    """Execute Plotly code and return (fig, error).

    The code runs in a namespace with df, go, px, pd, np available.
    It must assign a go.Figure to the variable 'fig'.

    Returns (fig, None) on success, (None, traceback_str) on failure.
    The error string is returned to Claude so it can self-correct.
    """
    namespace = {"df": df, "go": go, "px": px, "pd": pd, "np": np}
    try:
        exec(code, namespace)  # noqa: S102
        fig = namespace.get("fig")
        if not isinstance(fig, go.Figure):
            return None, "Code must assign a plotly Figure to 'fig'."
        return fig, None
    except Exception:
        return None, traceback.format_exc()
