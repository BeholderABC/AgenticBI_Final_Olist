from __future__ import annotations

from dataclasses import asdict

import pandas as pd
from sqlalchemy import text

from models.nlp_insights import build_nlp_insights
from utils.db import build_mysql_engine
from utils.settings import ARTIFACTS_DIR


def run_nlp_agent(*, sample_limit: int = 6000, cache_ttl_s: int = 3600) -> dict:
    """
    Pull reviews (score + text) from MySQL and produce NLP insights.
    """
    cache_path = ARTIFACTS_DIR / "nlp_insights_cache.json"
    try:
        import time
        now = time.time()
        if cache_path.exists() and (now - cache_path.stat().st_mtime) < cache_ttl_s:
            import json
            return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    engine = build_mysql_engine()
    sql = """
    SELECT review_score, review_comment_message
    FROM order_reviews
    WHERE review_comment_message IS NOT NULL AND review_comment_message <> ''
    LIMIT :lim
    """
    with engine.begin() as conn:
        df = pd.read_sql(text(sql), conn, params={"lim": sample_limit})
    insights = build_nlp_insights(df)
    out = asdict(insights)
    try:
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        import json
        cache_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out

