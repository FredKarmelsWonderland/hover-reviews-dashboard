"""Load reviews joined to their labels, for the dashboard and the agreement checks."""
import json

import pandas as pd

from .paths import APPSTORE_META, DATA, LABELS, REVIEWS
from .schema import codebook_version

LABELER_PREFERENCE = ["ai", "keywords-mock"]  # use real labels when they exist
PRIMARY_MODEL = "pass-a"  # pass A; the dashboard shows it by default

# Generic names for the two labeling passes, so the dashboard doesn't name a model vendor.
PASS_NAMES = {
    "pass-a": "Pass A (larger model)",
    "pass-b": "Pass B (smaller, different model)",
    "keywords": "Keyword stand-in",
}


def pass_name(model: str) -> str:
    return PASS_NAMES.get(model, model)


def load_reviews() -> pd.DataFrame:
    df = pd.read_csv(REVIEWS, dtype=str).fillna("")
    df["rating"] = df["rating"].astype(int)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df["year"] = df["date"].dt.year
    return df


def _rows() -> list[dict]:
    if not LABELS.exists():
        return []
    cb = codebook_version()
    rows = [json.loads(x) for x in LABELS.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r["codebook_version"] == cb]


def available_models() -> list[str]:
    """Models with labels for the current codebook: pass A first, then real labelers before the keyword
    stand-in, then the most reviews labeled first."""
    counts: dict[str, set] = {}
    rank: dict[str, int] = {}
    for r in _rows():
        counts.setdefault(r["model"], set()).add(r["review_id"])
        pref = LABELER_PREFERENCE.index(r["labeler"]) if r["labeler"] in LABELER_PREFERENCE else 99
        rank[r["model"]] = min(rank.get(r["model"], 99), pref)
    return sorted(counts, key=lambda m: (m != PRIMARY_MODEL, rank[m], -len(counts[m])))


def load_labels(model: str | None = None) -> tuple[pd.DataFrame, dict]:
    """One label row per review for one model (default: the first of available_models()).

    `mentions` holds only the mentions whose quote matched the review word for word."""
    rows = _rows()
    model = model or next(iter(available_models()), None)
    rows = [r for r in rows if r["model"] == model]
    if not rows:
        return pd.DataFrame(), {}
    latest: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: r["labeled_at"]):
        latest[r["review_id"]] = r
    out = []
    for rid, r in latest.items():
        lab, chk = r["label"], r["check"]
        out.append(
            {
                "review_id": rid,
                "mentions": chk["verified_mentions"],
                "stance": lab["stance"],
                "severity": int(lab.get("severity") or 0),
                "user_type": lab["user_type"],
                "invited_by": lab["invited_by"],
                "insurance_side": lab["invited_by"] == "insurer" or lab["user_type"] == "adjuster",
                "competitors": lab.get("competitors", []),
                "quotes_ok": chk["quotes_ok"],
                "quotes_failed": chk["quotes_failed"],
            }
        )
    info = {
        "labeler": rows[-1]["labeler"],
        "model": model,
        "pass_name": pass_name(model),
        "codebook_version": codebook_version(),
        "prompt_version": rows[-1]["prompt_version"],
        "n_labeled": len(out),
    }
    return pd.DataFrame(out), info


def mentions_long(labels: pd.DataFrame) -> pd.DataFrame:
    """One row per mention: the review's columns plus stage, sentiment, quote and tags."""
    if labels.empty:
        return pd.DataFrame(columns=["review_id", "stage", "sentiment", "quote", "tags"])
    m = labels.explode("mentions").dropna(subset=["mentions"]).reset_index(drop=True)
    parts = pd.DataFrame(list(m["mentions"]))
    return pd.concat([m.drop(columns=["mentions"]), parts[["stage", "sentiment", "quote", "tags"]]], axis=1)


def load_joined(model: str | None = None) -> tuple[pd.DataFrame, dict]:
    reviews = load_reviews()
    labels, info = load_labels(model=model)
    if labels.empty:
        return reviews.assign(labeled=False), info
    df = reviews.merge(labels, on="review_id", how="left")
    df["labeled"] = df["stance"].notna()
    return df, info


def store_meta() -> dict:
    """Overall store ratings (including star-only ratings) for both stores."""
    out = {}
    if APPSTORE_META.exists():
        a = json.loads(APPSTORE_META.read_text())
        out["app_store"] = {"rating": a["store_rating"], "count": f"{a['store_rating_count']:,}"}
    gp = DATA / "raw" / "google_play_meta.json"
    if gp.exists():
        g = json.loads(gp.read_text())
        out["google_play"] = {"rating": g["store_rating"], "count": g["store_rating_count_label"], "viewed": g["viewed"]}
    return out
