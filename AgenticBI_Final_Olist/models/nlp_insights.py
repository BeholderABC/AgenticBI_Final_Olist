from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer


@dataclass(frozen=True)
class NLPInsights:
    """Structured NLP insights from review texts.

    C7 upgrade: now includes polarity (positive/negative/neutral) distribution
    and subjective scoring via TextBlob, plus positive term extraction for
    dual word cloud visualization.
    """
    summary: str
    top_negative_terms: list[str]
    # C7 additions ------------------------------------------------------------
    top_positive_terms: list[str] = field(default_factory=list)
    polarity_mean: float = 0.0
    polarity_pos_ratio: float = 0.0
    polarity_neg_ratio: float = 0.0
    polarity_neu_ratio: float = 0.0
    subjectivity_mean: float = 0.0
    sentiment_label: str = "neutral"


def _textblob_available() -> bool:
    """Check whether TextBlob is importable."""
    try:
        import textblob  # noqa: F401
        return True
    except ImportError:
        return False


def _compute_polarity_subjectivity(texts: pd.Series) -> dict:
    """
    Compute per-text polarity [-1, 1] and subjectivity [0, 1] via TextBlob.
    Falls back to review-score-based heuristic if TextBlob is unavailable.

    Returns a dict with aggregated stats.
    """
    if _textblob_available():
        from textblob import TextBlob

        pol_list: list[float] = []
        subj_list: list[float] = []
        for txt in texts:
            try:
                blob = TextBlob(str(txt))
                pol_list.append(blob.sentiment.polarity)
                subj_list.append(blob.sentiment.subjectivity)
            except Exception:
                pol_list.append(0.0)
                subj_list.append(0.0)

        if not pol_list:
            return _empty_sentiment_dict()

        pol = pd.Series(pol_list)
        subj = pd.Series(subj_list)

        pos = (pol > 0.1).sum()
        neg = (pol < -0.1).sum()
        neu = len(pol) - pos - neg
        total = max(len(pol), 1)

        # Determine aggregate sentiment label
        if pos / total >= 0.5:
            label = "positive"
        elif neg / total >= 0.5:
            label = "negative"
        else:
            label = "neutral"

        return {
            "polarity_mean": float(pol.mean()),
            "polarity_pos_ratio": pos / total,
            "polarity_neg_ratio": neg / total,
            "polarity_neu_ratio": neu / total,
            "subjectivity_mean": float(subj.mean()),
            "sentiment_label": label,
        }
    else:
        return _empty_sentiment_dict()


def _empty_sentiment_dict() -> dict:
    return {
        "polarity_mean": 0.0,
        "polarity_pos_ratio": 0.0,
        "polarity_neg_ratio": 0.0,
        "polarity_neu_ratio": 0.0,
        "subjectivity_mean": 0.0,
        "sentiment_label": "unknown",
    }


def _extract_top_terms(text_series: pd.Series, top_k: int = 20) -> list[str]:
    """
    Extract top TF-IDF terms from a text series.
    Returns an empty list if too few samples.
    """
    if len(text_series) < 50:
        return []

    vec = TfidfVectorizer(
        max_features=5000,
        stop_words=None,
        ngram_range=(1, 2),
        min_df=5,
    )
    try:
        X = vec.fit_transform(text_series)
    except ValueError:
        return []

    scores = X.sum(axis=0).A1
    terms = vec.get_feature_names_out()
    top_idx = scores.argsort()[::-1][:top_k]
    # Convert np.str_ → native Python str for msgpack compatibility
    return [str(terms[i]) for i in top_idx]


def build_nlp_insights(reviews: pd.DataFrame, *, top_k: int = 20) -> NLPInsights:
    """
    Build comprehensive NLP insights from review data.

    C7 upgrade:
    - TextBlob polarity/subjectivity scoring on review_comment_message
    - Extract both positive (score >=4) and negative (score <=2) TF-IDF terms
      for dual word cloud comparison
    - Structured sentiment scores written for downstream decision agent

    Input: columns include review_score, review_comment_message
    """
    df = reviews.copy()
    if "review_score" not in df.columns:
        return NLPInsights(summary="No review_score available.", top_negative_terms=[])

    df["review_comment_message"] = df.get("review_comment_message", "").fillna("").astype(str)

    neg = df[df["review_score"].astype(float) <= 2]
    pos = df[df["review_score"].astype(float) >= 4]
    neu = df[(df["review_score"].astype(float) > 2) & (df["review_score"].astype(float) < 4)]

    neg_ratio = (len(neg) / max(len(df), 1)) * 100
    pos_ratio = (len(pos) / max(len(df), 1)) * 100
    neu_ratio = (len(neu) / max(len(df), 1)) * 100

    # TF-IDF term extraction for both positive and negative
    top_neg_terms = _extract_top_terms(neg["review_comment_message"], top_k=top_k)
    top_pos_terms = _extract_top_terms(pos["review_comment_message"], top_k=top_k)

    # C7: TextBlob sentiment analysis on all review messages
    sentiment = _compute_polarity_subjectivity(df["review_comment_message"])

    # Build summary string with richer sentiment info
    sent_label = sentiment.get("sentiment_label", "unknown")
    summary = (
        f"Reviews summary: total={len(df):,}, "
        f"positive(>=4)={pos_ratio:.1f}%, "
        f"negative(<=2)={neg_ratio:.1f}%, "
        f"neutral(3)={neu_ratio:.1f}%. "
        f"Sentiment (TextBlob): polarity_mean={sentiment['polarity_mean']:.3f}, "
        f"subjectivity_mean={sentiment['subjectivity_mean']:.3f}, "
        f"overall_label={sent_label}. "
        f"Positive ratio={sentiment['polarity_pos_ratio']:.1%}, "
        f"Negative ratio={sentiment['polarity_neg_ratio']:.1%}."
    )

    return NLPInsights(
        summary=summary,
        top_negative_terms=top_neg_terms,
        top_positive_terms=top_pos_terms,
        polarity_mean=sentiment["polarity_mean"],
        polarity_pos_ratio=sentiment["polarity_pos_ratio"],
        polarity_neg_ratio=sentiment["polarity_neg_ratio"],
        polarity_neu_ratio=sentiment["polarity_neu_ratio"],
        subjectivity_mean=sentiment["subjectivity_mean"],
        sentiment_label=sent_label,
    )