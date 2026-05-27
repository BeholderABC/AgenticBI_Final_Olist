from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

try:
    from statsmodels.tsa.statespace.sarimax import SARIMAX
except Exception:  # pragma: no cover
    SARIMAX = None


@dataclass(frozen=True)
class ForecastResult:
    df: pd.DataFrame  # columns: ds, yhat, yhat_lower, yhat_upper


def forecast_6_weeks(monthly_sales: pd.DataFrame, *, fast_mode: bool = False) -> ForecastResult:
    """
    Input: monthly_sales with columns: year_month (YYYY-MM), total_gmv
    Output: weekly forecast for next 6 weeks (42 days).
    """
    df = monthly_sales.copy()
    df["ds"] = pd.to_datetime(df["year_month"] + "-01")
    df = df.sort_values("ds")
    y = df.set_index("ds")["total_gmv"].astype(float)

    # interpolate to weekly series (simple smoothing)
    weekly = y.resample("W-SUN").interpolate(method="time")

    horizon = 6  # weeks
    future_index = pd.date_range(
        start=weekly.index.max() + timedelta(days=7),
        periods=horizon,
        freq="W-SUN",
    )

    if fast_mode or SARIMAX is None or len(weekly) < 20:
        # fallback: naive with recent mean and wide interval
        base = float(weekly.tail(8).mean()) if len(weekly) else float(y.mean())
        yhat = np.full(horizon, base, dtype=float)
        lower = yhat * 0.85
        upper = yhat * 1.15
    else:
        model = SARIMAX(
            weekly,
            order=(1, 1, 1),
            seasonal_order=(1, 0, 1, 52),
            enforce_stationarity=False,
            enforce_invertibility=False,
        )
        res = model.fit(disp=False)
        pred = res.get_forecast(steps=horizon)
        yhat = pred.predicted_mean.to_numpy(dtype=float)
        conf = pred.conf_int(alpha=0.2)  # 80% interval
        lower = conf.iloc[:, 0].to_numpy(dtype=float)
        upper = conf.iloc[:, 1].to_numpy(dtype=float)

    out = pd.DataFrame(
        {
            "ds": future_index,
            "yhat": yhat,
            "yhat_lower": lower,
            "yhat_upper": upper,
        }
    )
    return ForecastResult(df=out)

