from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass(frozen=True)
class NLPInsights:
    summary: str
    top_negative_terms: list[str]


def build_nlp_insights(reviews: pd.DataFrame, *, top_k: int = 20) -> NLPInsights:
    """
    Minimal NLP: use review_score as sentiment proxy; extract TF-IDF terms from negative texts.
    Input: columns include review_score, review_comment_message
    """
    df = reviews.copy()
    if "review_score" not in df.columns:
        return NLPInsights(summary="No review_score available.", top_negative_terms=[])

    df["review_comment_message"] = df.get("review_comment_message", "").fillna("").astype(str)

    neg = df[df["review_score"].astype(float) <= 2]
    pos = df[df["review_score"].astype(float) >= 4]

    neg_ratio = (len(neg) / max(len(df), 1)) * 100
    pos_ratio = (len(pos) / max(len(df), 1)) * 100

    top_terms: list[str] = []
    if len(neg) >= 50:
        vec = TfidfVectorizer(
            max_features=5000,
            stop_words=None,
            ngram_range=(1, 2),
            min_df=5,
        )
        X = vec.fit_transform(neg["review_comment_message"])
        scores = X.sum(axis=0).A1
        terms = vec.get_feature_names_out()
        top_idx = scores.argsort()[::-1][:top_k]
        top_terms = [terms[i] for i in top_idx]

    summary = (
        f"Reviews summary: total={len(df):,}, positive(>=4)={pos_ratio:.1f}%, "
        f"negative(<=2)={neg_ratio:.1f}%."
    )
    return NLPInsights(summary=summary, top_negative_terms=top_terms)

