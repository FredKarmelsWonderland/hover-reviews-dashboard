"""Hover app reviews: how few complaints are about estimates, where the rest land, and why Estimates might leak.

Each review is split into mentions (codebook v3): every stage it praises, complains about or makes a suggestion on
counts separately, with an exact quote.

Run: uv run streamlit run app.py
"""
import html
import json
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from hover_reviews.data import available_models, load_joined, load_labels, mentions_long, pass_name, store_meta
from hover_reviews.paths import PASS_AGREEMENT
from hover_reviews.schema import BEFORE_ESTIMATE, BEFORE_RESULTS, STAGES, TAGS, codebook_text

st.set_page_config(page_title="Hover Review Journey", layout="wide")

# Reference data-viz palette (light slots), used by role.
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#898781"
STORE_NAMES = {"app_store": "App Store", "google_play": "Google Play"}
STAGE_NAMES = {
    "getting_in": "1. Getting in",
    "capture": "2. Capture",
    "model_delivery": "3. Model delivery",
    "measurements": "4. Measurements",
    "design": "5. Design",
    "estimate_proposal": "6. Estimate & proposal",
    "paying": "Paying (any point)",
    "general": "No stage named",
}
TAG_NAMES = {
    "crash_bug": "Crash or bug",
    "lost_work": "Lost work",
    "wrong_output": "Wrong output",
    "waiting": "Waiting",
    "cant_do_it": "Couldn't do what they wanted",
    "hard_to_use": "Hard to use",
    "update_worse": "Update made it worse",
    "support": "Support",
    "cost": "Cost",
}
SENTIMENTS = ["complaint", "praise", "suggestion"]
WHO_NAMES = {"contractor": "contractor", "adjuster": "adjuster", "homeowner": "homeowner", "other_unclear": "reviewer"}
FUNNEL_STAGES = [s for s in STAGES if s != "general"]
INTEGRATION_WORDS = r"integrat|acculynx|jobnimbus|\bcrm\b|export|xactimate|chief architect|quickbooks"
REDESIGN_DATE = pd.Timestamp("2026-07-22", tz="UTC")  # Hover's new 3D experience (help.hover.to article 15327278)
REDESIGN_URL = "https://help.hover.to/en/articles/15327278-introducing-the-new-3d-experience"

# Quotes from earlier stages: (review_id, exact excerpt). Each is checked against the review text before it's shown.
EARLIER_QUOTES = [
    ("as-14534457479", "I constantly have to go back to properties and retake photos because it fails upload."),
    ("as-12991428293", "Hover was recommended by a contractor who we are getting a bid from on siding. It made a bad first impression and wasted a lot of my time."),
    ("gp-df36dee3-b91c-4478-9f94-20663d3acde9", "they do not have all the shingles and siding that are sold by g a f and CertainTeed"),
    ("as-14093979248", "Then if you do a job it’s $89 extra per job. Plus if they deem it “complex” they will add another $59."),
    ("as-14056433749", "As a contractor, this has a huge impact on how timely I am getting customers estimates."),
    ("gp-a558f3c3-c960-4db9-a1b0-44e504cd8255", "I can not find anything that will let me find sq. Footage of bedrooms or office rooms"),
]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a proportion k/n; behaves sensibly at small n."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def nice_stage(s: str) -> str:
    return STAGE_NAMES.get(s, s)


def nice_tag(t: str) -> str:
    return TAG_NAMES.get(t, t)


def style(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=40, b=8),
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13),
        barcornerradius=4,
        bargap=0.3,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hoverlabel=dict(font_size=13),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(137,135,129,0.25)", zeroline=False)
    return fig


def _norm(s: str) -> str:
    s = s.translate(str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'}))
    return re.sub(r"\s+", " ", s).strip().lower()


def md_safe(text: str) -> str:
    """One line, with dollar signs escaped so Streamlit doesn't read them as math."""
    return " ".join(text.split()).replace("$", "\\$")


def quote_card(df: pd.DataFrame, rid: str, excerpt: str) -> str | None:
    row = df[df["review_id"] == rid]
    if row.empty or _norm(excerpt) not in _norm(row.iloc[0]["title"] + " " + row.iloc[0]["text"]):
        return None
    r = row.iloc[0]
    who = WHO_NAMES.get(r.get("user_type"), "reviewer") if isinstance(r.get("user_type"), str) else "reviewer"
    return f"> “{md_safe(excerpt)}”\n>\n> — {who}, {STORE_NAMES[r['source']]}, {r['date']:%b %Y}, {r['rating']}★"


def highlight(text: str, quote: str) -> str:
    """HTML-escaped text with the labeled quote marked, matching curly or straight quotes and any spacing."""
    def clean(t: str) -> str:
        return html.escape(" ".join(t.split())).replace("$", "&#36;")
    body = clean(text)
    parts = []
    for ch in " ".join(quote.split()).strip(" .,!?;:\"'"):
        if ch in "'’‘":
            parts.append("(?:'|’|‘|&#x27;)")
        elif ch in '"“”':
            parts.append('(?:"|“|”|&quot;)')
        elif ch == " ":
            parts.append(r"\s+")
        else:
            parts.append(re.escape(html.escape(ch)))
    if not parts:
        return body
    return re.sub("(" + "".join(parts) + ")", r'<mark style="background:rgba(235,104,52,0.35);color:inherit">\1</mark>',
                  body, count=1, flags=re.I)


def estimate_card(r: pd.Series) -> str:
    """A review card in the estimate bar's orange, with the labeled words marked."""
    title = f"<b>{html.escape(' '.join(r['title'].split()))}.</b> " if r["title"].strip() else ""
    who = WHO_NAMES.get(r["user_type"], "reviewer")
    return (f'<div style="border-left:4px solid {ORANGE};background:rgba(235,104,52,0.10);padding:0.75rem 1rem;'
            f'border-radius:6px;margin-bottom:0.75rem">{title}{highlight(r["text"], r["quote"])}'
            f'<div style="margin-top:0.5rem;opacity:0.7;font-size:0.9rem">— {who}, {STORE_NAMES[r["source"]]}, '
            f'{r["date"]:%b %Y}, {r["rating"]}★</div></div>')


def shares(stages: pd.Series) -> tuple[float, float]:
    """The share about estimates and the share before the estimate stage."""
    if stages.empty:
        return 0.0, 0.0
    return (stages == "estimate_proposal").mean(), stages.isin(BEFORE_ESTIMATE).mean()


@st.cache_data
def other_pass_mentions(shown: str) -> pd.DataFrame:
    other = next((m for m in available_models() if m not in (shown, "keywords")), None)
    lab, _ = load_labels(model=other) if other else (pd.DataFrame(), {})
    return mentions_long(lab) if len(lab) else pd.DataFrame()


@st.cache_data
def get_data(model):
    df, info = load_joined(model)
    return df, info, store_meta()


# ---------------- Sidebar: which reviews ----------------
models = available_models()
chosen_model = st.sidebar.selectbox("Labels from", models, format_func=pass_name) if len(models) > 1 else None
df_all, info, meta = get_data(chosen_model)

since = st.sidebar.selectbox("Reviews since", [2023, 2024, 2025, 2016], index=0,
                             format_func=lambda y: "all years" if y == 2016 else f"January 1, {y}")
drop_insurance = st.sidebar.checkbox("Leave out the insurance side", value=True,
                                     help="Homeowners sent by an insurer, and adjusters. Estimates is a contractor feature.")
contractors_only = st.sidebar.checkbox("Contractors only", value=False,
                                       help="Only reviewers who say they're contractors, plus homeowners a contractor sent. "
                                            "Small: most reviewers don't say who they are.")
st.sidebar.caption("Labels exist for reviews since January 1, 2023. Older reviews count in star ratings only.")

df = df_all[df_all["year"] >= since].copy()
labeled_all = df[df["labeled"]].copy() if "labeled" in df else df.iloc[0:0]
labeled = labeled_all
if drop_insurance and len(labeled):
    labeled = labeled[~labeled["insurance_side"].astype(bool)]
if contractors_only and len(labeled):
    labeled = labeled[(labeled["user_type"] == "contractor") | (labeled["invited_by"] == "contractor")]
scope = []
if drop_insurance:
    scope.append("insurance side left out")
if contractors_only:
    scope.append("contractors only")
scope_txt = f" ({', '.join(scope)})" if scope else ""
since_txt = "all years" if since == 2016 else f"since January 1, {since}"

ment = mentions_long(labeled) if len(labeled) else pd.DataFrame(columns=["review_id", "stage", "sentiment", "quote", "tags"])
comp = ment[ment["sentiment"] == "complaint"]  # complaint mentions, including "no stage named"
staged = comp[comp["stage"].isin(FUNNEL_STAGES)]  # complaint mentions that point to a stage
est_df = staged[staged["stage"] == "estimate_proposal"]


def overview_notes() -> list[str]:
    """How to read the Overview, and the checks on its numbers."""
    if staged.empty:
        return []
    n_before = int(staged["stage"].isin(BEFORE_ESTIMATE).sum())
    lo_x, hi_x = wilson(len(est_df), len(staged))
    n_general = int((comp["stage"] == "general").sum())
    notes = [
        f"**What the Overview counts.** Each review is split into mentions: every part of the journey it complains "
        f"about, praises or makes a suggestion on counts separately, with the exact words that show it. The Overview "
        f"counts complaint mentions only. There are {len(staged)} that point to a stage, from "
        f"{staged['review_id'].nunique()} reviews, {since_txt}{scope_txt}; {n_general} more complain about the app in "
        f"general. {len(est_df)} are about estimates or proposals (95% confidence interval {lo_x:.1%} to {hi_x:.1%}), "
        f"and {n_before}, or {n_before / len(staged):.0%}, are about steps before the estimate. A mention shows where "
        "someone had a bad experience, not proof they gave up there."
    ]
    checks = []
    sug = ment[ment["sentiment"].isin(["complaint", "suggestion"]) & ment["stage"].isin(FUNNEL_STAGES)]
    e, before = shares(sug["stage"])
    checks.append(f"Counting suggestions (\"I wish...\") as complaints too gives {e:.0%} about estimates and {before:.0%} "
                  "before the estimate.")
    other = other_pass_mentions(info.get("model", ""))
    if not other.empty:
        o = other[other["review_id"].isin(set(labeled["review_id"])) & (other["sentiment"] == "complaint")
                  & other["stage"].isin(FUNNEL_STAGES)]
        both = staged.merge(o[["review_id", "stage"]], on=["review_id", "stage"])
        if len(o) and len(both):
            e1, b1 = shares(o["stage"])
            e2, b2 = shares(both["stage"])
            checks.append(f"A second, independent labeling pass gives {e1:.0%} and {b1:.0%}. Counting only the "
                          f"{len(both)} complaint mentions both passes found gives {e2:.0%} and {b2:.0%}.")
    notes.append("**Checks.** " + " ".join(checks))
    notes.append("**Keep in mind.** People who write reviews are usually unhappy, so this shows what goes wrong, not "
                 "how often. Starter accounts can try estimating, but the full Estimates tools come with Pro and higher "
                 "plans, and reviews don't say who's on which plan. Hover redesigned the 3D and estimate flow on July "
                 "22, 2026, so most of these reviews describe the old flow.")
    src = ", ".join(f"{v} {STORE_NAMES[k]}" for k, v in df["source"].value_counts().items())
    notes.append(f"**The data.** {len(df_all)} written reviews in all, {len(df)} of them {since_txt} ({src}). App Store "
                 "reviews come from Apple's official review feed; Google Play reviews come from an export of Hover's "
                 "listing.")
    return notes


if info.get("labeler") == "keywords-mock":
    st.warning("These labels come from keyword rules used to test the pipeline, not from the AI labeler.", icon="⚠️")
elif not info:
    st.warning("No labels yet. Run the labeling step first.", icon="⚠️")

tabs = st.tabs(["Overview", "Hypotheses why Estimates usage is low", "User research", "Journey stages",
                "Review explorer",
                "Method & validation"])

# ---------------- Overview ----------------
with tabs[0]:
    if staged.empty:
        st.markdown("## Where review complaints land in the journey")
        st.write("No labels yet.")
    else:
        st.markdown("## Hover App reviews: Complaints about Estimate & Proposal are rare")
        upstream = staged["stage"].isin(BEFORE_ESTIMATE).mean()
        st.markdown(
            f'<ul style="font-size:1.15rem;margin-top:-0.4rem"><li>{upstream:.0%} of complaints are upstream of Estimate '
            "&amp; proposal</li><li>If people aren't complaining about Estimate &amp; proposal itself, what causes "
            "leakage at that stage?</li></ul>",
            unsafe_allow_html=True,
        )
        k = staged["stage"].value_counts().reindex(FUNNEL_STAGES, fill_value=0)
        share = k / len(staged)
        est = [x == "estimate_proposal" for x in FUNNEL_STAGES]  # the stage the job is about, highlighted
        fig = go.Figure(go.Bar(
            y=[f"<b>{nice_stage(x)}</b>" if e else nice_stage(x) for x, e in zip(FUNNEL_STAGES, est)],
            x=share.values, orientation="h",
            marker_color=[ORANGE if e else BLUE for e in est],
            text=[f"<b>{v:.0%}</b>" if e else f"{v:.0%}" for v, e in zip(share.values, est)],
            textposition="outside", cliponaxis=False,
            customdata=k.values, hovertemplate="%{y}: %{x:.0%} (%{customdata} complaints)<extra></extra>",
        ))
        st.markdown(f"**Where complaints land in the journey**, {since_txt} "
                    f"({', '.join([f'n = {len(staged)} complaints from {staged.review_id.nunique()} reviews'] + scope)})")
        fig.update_yaxes(autorange="reversed", showgrid=False)
        fig.update_xaxes(range=[0, share.max() * 1.25], visible=False)
        st.plotly_chart(style(fig, 380), width="stretch")

        cols = st.columns(2)
        for i, (_, r) in enumerate(est_df.sort_values("date", ascending=False).head(6).iterrows()):
            cols[i % 2].markdown(estimate_card(r), unsafe_allow_html=True)
        with st.expander("Complaints from earlier stages"):
            for rid, q in EARLIER_QUOTES:
                if card := quote_card(df, rid, q):
                    st.markdown(card)
        n_after = int((labeled["date"] >= REDESIGN_DATE).sum())
        st.markdown(
            '<div style="border:1px solid rgba(137,135,129,0.45);border-radius:8px;padding:0.6rem 0.9rem;margin:0.8rem 0 '
            f'0.8rem;font-size:0.92rem"><b>Redesigned in July.</b> On July 22, 2026, Hover released a '
            f'<a href="{REDESIGN_URL}" target="_blank">new 3D experience</a>: measurements are built into the 3D view with '
            "no switching between modes, product choices are guided step by step, and applied products carry into an "
            "estimate, with templates and pricing mapped automatically. It's rolling out in phases. Only "
            f"{n_after} of the {len(labeled)} reviews here come after it, so they mostly describe the old flow.</div>",
            unsafe_allow_html=True,
        )
        st.caption("Each review is split into mentions, so a review that praises one stage and complains about another "
                   "counts at both. This chart counts complaint mentions only, judged mainly from what reviewers say "
                   "rather than their star rating; praise and suggestions (\"I wish...\") aren't counted. Written reviews "
                   "skew unhappy and don't say which plan anyone is on (the full Estimates tools need Pro or higher). "
                   "Details and checks are on the Method & validation tab.")

# ---------------- Hypotheses why Estimates usage is low ----------------
with tabs[1]:
    def complaints_at(stages: set, tag: str | None = None) -> pd.DataFrame:
        hit = staged[staged["stage"].isin(stages)]
        return hit[hit["tags"].apply(lambda ts: tag in ts)] if tag else hit

    def esc(t: str) -> str:
        return html.escape(" ".join(str(t).split())).replace("$", "&#36;")

    def quote_list(rows: pd.DataFrame, limit: int = 12) -> str:
        """The quotes behind a count, newest first, for a chip that opens on click."""
        items = []
        for _, r in rows.sort_values("date", ascending=False).head(limit).iterrows():
            who = WHO_NAMES.get(r["user_type"], "reviewer")
            items.append(f'<li style="margin:0.2rem 0">“{esc(r["quote"])}” <span style="opacity:0.65">— {who}, '
                         f'{STORE_NAMES[r["source"]]}, {r["date"]:%b %Y}</span></li>')
        more = (f'<div style="opacity:0.65">...and {len(rows) - limit} more in the Review explorer.</div>'
                if len(rows) > limit else "")
        return f'<ul style="margin:0.3rem 0 0.2rem;padding-left:1.1rem">{"".join(items)}</ul>{more}'

    # Reviews that mention integrations or exports at all, with the words around the first match.
    blob = labeled["title"] + " " + labeled["text"]
    integ = labeled[blob.str.contains(INTEGRATION_WORDS, case=False, regex=True)].copy()

    def around(text: str) -> str:
        m = re.search(INTEGRATION_WORDS, text, flags=re.I)
        lo, hi = max(0, m.start() - 70), min(len(text), m.end() + 70)
        return ("..." if lo else "") + text[lo:hi].strip() + ("..." if hi < len(text) else "")

    integ["quote"] = [around(t + " " + x) for t, x in zip(integ["title"], integ["text"])]
    paying = complaints_at({"paying"})
    waiting = complaints_at({"model_delivery"}, "waiting")
    wrong = complaints_at({"measurements"}, "wrong_output")
    missing = complaints_at({"design"}, "cant_do_it")
    before_model = complaints_at(BEFORE_RESULTS)

    def chip(text: str, kind: str, opens: bool = False) -> str:
        colors = {"big": (ORANGE, "rgba(235,104,52,0.15)"), "small": (BLUE, "rgba(42,120,214,0.12)"),
                  "some": (GRAY, "rgba(137,135,129,0.15)"), "none": (GRAY, "transparent")}
        fg, bg = colors[kind]
        caret = '<span class="caret">▸</span> ' if opens else ""
        return (f'<span style="display:inline-block;border:1px solid {fg};background:{bg};border-radius:8px;'
                f'padding:0.05rem 0.55rem;font-size:0.8rem;margin:0.25rem 0">{caret}{text}</span>')

    # Chips that open: no default disclosure arrow (it wraps onto its own line); a caret inside the chip instead.
    st.markdown("<style>summary.chipsum{list-style:none;display:block;cursor:pointer}"
                "summary.chipsum::-webkit-details-marker{display:none}"
                ".caret{display:inline-block;transition:transform 0.15s}"
                "details[open]>summary.chipsum .caret{transform:rotate(90deg)}</style>", unsafe_allow_html=True)

    def card(title: str, what: str, evidence: str, kind: str, test: str, accent: str | None = None,
             first: bool = False, note: str = "", quotes: pd.DataFrame | None = None) -> str:
        edge = accent or "rgba(137,135,129,0.45)"
        badge = (f'<span style="float:right;font-size:0.72rem;font-weight:600;color:#fff;background:{BLUE};'
                 'border-radius:6px;padding:0.1rem 0.45rem;margin-left:0.4rem">Test first</span>' if first else "")
        return (f'<div style="border:1px solid rgba(137,135,129,0.35);border-left:4px solid {edge};border-radius:8px;'
                f'padding:0.7rem 0.9rem;margin-bottom:0.7rem"><div style="font-weight:600">{badge}{title}</div>'
                f'<div style="font-size:0.92rem;margin-top:0.2rem">{what}</div>'
                + (f'<div style="font-size:0.85rem;margin-top:0.35rem">{note}</div>' if note else "")
                + ("" if not evidence or (quotes is not None and not len(quotes)) else
                   f'<details style="margin:0.1rem 0"><summary class="chipsum">{chip(evidence, kind, opens=True)}'
                   f'</summary><div style="font-size:0.85rem">{quote_list(quotes)}</div></details>'
                   if quotes is not None else chip(evidence, kind))
                + f'<details style="font-size:0.85rem;margin-top:0.15rem"><summary style="cursor:pointer;opacity:0.8">'
                f'To test</summary><div style="opacity:0.8;margin-top:0.2rem">{test[:1].upper() + test[1:]}</div>'
                "</details></div>")

    st.markdown('<div style="font-size:1.15rem;margin:0.3rem 0 0.8rem"><i><b>Note:</b> 3D estimates was redesigned '
                "recently. Has that eliminated friction and improved usage?</i></div>",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    c1.markdown("**Before an estimate is started**")
    c1.markdown(
        card("They only wanted measurements",
             "Not every model is meant to become an estimate. Many people only want the measurements, and counting "
             "them as failed estimates makes Estimates look worse than it is.",
             "", "none",
             "split non-estimators into never meant to, couldn't on their plan, and started then stopped; look at "
             "whether accounts ever open Design or Estimates, and ask in the exit survey", first=True)
        + card("Pricing happens in the CRM",
             "Contractors send Hover's measurements to their CRM and build the price there, so the estimate never "
             "happens in Hover.",
             "Top suspect, untested", "big",
             "share of delivered models exported to a CRM versus estimated in Hover", accent=ORANGE, first=True)
        + card("Plan and price",
               "Starter accounts can only try estimating; the full tools need Pro or higher.",
               f"Reviews: {len(paying)} complaints about what Hover costs", "some",
               "the funnel by plan, and upgrades after a first estimate", first=True, quotes=paying)
        + card("Setup effort",
               "Pricing catalogs, margins and templates have to be set up before the first estimate.",
               "", "none",
               "conversion before and after pricing is set up; time to first estimate",
               note="Since the July redesign, \"Review estimate\" maps templates and pricing automatically, which may "
                    "shrink this.")
        + card("Timing",
               "The model arrives hours after the visit, so the one-visit close doesn't happen.",
               f"Reviews: {len(waiting)} complaints about waiting for the model", "some",
               "estimate rate by turnaround time, within the same account", first=True, quotes=waiting)
        + card("Missing products",
               "The catalog lacks the products they sell, so the estimate gets built elsewhere.",
               f"Reviews: {len(missing)} design complaints about missing options or products",
               "some", "failed product searches; drop-off by trade", quotes=missing)
        + card("The estimate step itself",
               "The Estimates experience is confusing, slow or broken.",
               f"Small in reviews: {len(est_df)} complaint mentions at estimate &amp; proposal", "small",
               "drop-off and errors inside the Estimates flow, before and after the redesign", quotes=est_df,
               note="Redesigned on July 22, 2026 to remove switching between modes; the reviews mostly predate it."),
        unsafe_allow_html=True,
    )
    c2.markdown("**Between estimate and proposal**")
    c2.markdown(
        card("Trust in the numbers",
             "Contractors don't trust the auto-generated measurements enough to price from them.",
             f"Reviews: {len(wrong)} complaints about wrong measurements", "some",
             "measurement edits, pitch overrides and abandonment by roof complexity", quotes=wrong)
        + card("Integrations and exports",
               "The estimate needs to end up in another tool, and getting it there is hard.",
               f"Reviews: {len(integ)} mention integrations, exports or CRMs at all", "some",
               "export and integration usage after an estimate is built", quotes=integ),
        unsafe_allow_html=True,
    )
    c3.markdown("**Between proposal and signature**")
    c3.markdown(
        card("Value isn't clear",
             "Contractors don't see Hover-built estimates winning more jobs, so they stop using them.",
             "", "none",
             "win rates for Hover-built estimates versus others")
        + card("Homeowner doesn't sign",
               "The proposal goes out but the homeowner chooses another bid or waits.",
               "", "none",
               "proposal-to-signature rate by trade, price and time to send"),
        unsafe_allow_html=True,
    )
    st.markdown(
        card("Upstream app problems (before a model exists)",
             "Login, capture and upload problems stop people before there's a model to estimate from.",
             f"Common in reviews ({len(before_model)} of {len(staged)} complaint mentions come before a model "
             "exists), but they sit before the 3D-to-Estimates funnel starts", "small",
             "the share of started projects that never get a model, by plan and trade", quotes=before_model),
        unsafe_allow_html=True,
    )
    st.caption("Counts come from the same reviews as the Overview. A count of zero or a few means reviewers rarely bring "
               "it up, not that it doesn't happen: most of these causes happen in the office or the CRM, where app "
               "reviewers don't look.")
    st.markdown(
        f'<div style="border:1px solid {BLUE};background:rgba(42,120,214,0.08);border-radius:8px;padding:0.75rem 1rem;'
        'margin-top:1rem"><div style="font-weight:600;margin-bottom:0.3rem">Before blaming any leak, check the '
        'finish line</div><ul style="margin:0;padding-left:1.2rem;font-size:0.93rem">'
        "<li><b>The finish line:</b> what counts as success? An estimate started, a proposal sent, the job signed, or "
        "a clean handoff to the contractor's CRM? If contractors win the job but price it in their CRM, that isn't a "
        "leak.</li><li><b>The benchmark:</b> low compared with what? A target, an earlier cohort, or a guess?</li>"
        "<li><b>The segments:</b> is it low everywhere, or only for some trades, plans or company sizes?</li>"
        "<li><b>Intent:</b> did they ever mean to estimate in Hover? Someone who only wanted measurements isn't a "
        "failed estimate; only people who start an estimate and stop are a true leak.</li></ul>"
        '<div style="font-size:0.85rem;opacity:0.75;margin-top:0.35rem">Cards marked <b>Test first</b> can be checked '
        "with data Hover already has, in the first couple of weeks.</div></div>",
        unsafe_allow_html=True,
    )

# ---------------- User research ----------------
with tabs[2]:
    st.markdown("## Numbers show where people stop. Talking to them shows why.")
    st.caption("Funnel data can't see a contractor's reasons, so pair it with direct research at the biggest leak.")
    qual = [
        ("One-question exit survey", "Shown when someone leaves the estimate flow: \"How will you price this job?\" "
         "(in Hover, my CRM, a spreadsheet, I don't trust the measurements yet).",
         "Sizes the causes directly, at the moment of drop-off."),
        ("Contractor interviews", "Five to eight per segment (trade, plan, company size), including people who "
         "stopped using Estimates.", "Finds reasons nobody thought to instrument."),
        ("Ride-alongs", "Watch a sales rep run a real in-home appointment from capture to proposal.",
         "Shows where timing, trust and the CRM actually come into the visit."),
        ("Focus groups", "Small groups of sales reps or office estimators from the same trade, reacting to the "
         "Estimates flow and to concept changes.", "Surfaces shared objections and tests ideas before building them."),
        ("Support tickets and sales calls", "Classify ticket text, cancellation reasons and call notes by the same "
         "stages, at scale.", "The same method as these reviews, on far better data."),
    ]
    q1, q2, q3 = st.columns(3)
    for i, (title, what, why) in enumerate(qual):
        (q1, q2, q3)[i % 3].markdown(
            f'<div style="border:1px solid rgba(137,135,129,0.35);border-radius:8px;padding:0.7rem 0.9rem;'
            f'margin-bottom:0.7rem"><div style="font-weight:600">{title}</div><div style="font-size:0.92rem;'
            f'margin-top:0.2rem">{what}</div><div style="font-size:0.85rem;opacity:0.75;margin-top:0.3rem">{why}</div>'
            "</div>",
            unsafe_allow_html=True,
        )

# ---------------- Journey stages ----------------
with tabs[3]:
    if comp.empty:
        st.write("No labels yet.")
    else:
        stages_shown = FUNNEL_STAGES + ["general"]
        st.markdown("## Complaints and praise at each stage")
        st.caption(f"{len(comp)} complaint mentions from {comp['review_id'].nunique()} reviews {since_txt}{scope_txt}.")
        long = comp.explode("tags").dropna(subset=["tags"])
        grid = (long.groupby(["stage", "tags"])["review_id"].nunique().unstack(fill_value=0)
                .reindex(index=stages_shown, columns=TAGS, fill_value=0))
        fig = go.Figure(go.Heatmap(
            z=grid.values, x=[nice_tag(t) for t in grid.columns], y=[nice_stage(s) for s in grid.index],
            colorscale=[[0, "#f4f8fd"], [1, BLUE]], text=grid.values, texttemplate="%{text}",
            hovertemplate="%{y} · %{x}: %{z} complaints<extra></extra>", showscale=False, xgap=2, ygap=2,
        ))
        fig.update_layout(title="Problem type at each stage")
        fig.update_yaxes(autorange="reversed", showgrid=False)
        st.plotly_chart(style(fig, 420), width="stretch")
        st.caption("Complaint mentions at each stage, by tag. A complaint can have several tags.")

        st.markdown("**Praise and complaints at each stage.** Complaints alone hide where things work.")
        pc = (ment.groupby(["stage", "sentiment"]).size().unstack(fill_value=0)
              .reindex(index=stages_shown, columns=SENTIMENTS, fill_value=0))
        ylab = [nice_stage(x) for x in pc.index]
        fig = go.Figure()
        fig.add_bar(y=ylab, x=-pc["complaint"], orientation="h", name="Complaints", marker_color=ORANGE,
                    customdata=pc["complaint"], text=pc["complaint"], textposition="outside", cliponaxis=False,
                    hovertemplate="%{y}: %{customdata} complaints<extra></extra>")
        fig.add_bar(y=ylab, x=pc["praise"], orientation="h", name="Praise", marker_color=BLUE,
                    text=pc["praise"], textposition="outside", cliponaxis=False,
                    hovertemplate="%{y}: %{x} praise<extra></extra>")
        m = int(pc[["complaint", "praise"]].values.max() * 1.2) + 1
        fig.update_layout(barmode="relative")
        fig.update_xaxes(range=[-m, m], tickvals=[-(m // 2), 0, m // 2], ticktext=[str(m // 2), "0", str(m // 2)],
                         zeroline=True, zerolinecolor=GRAY)
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(style(fig, 380), width="stretch")
        top_sug = pc["suggestion"].idxmax() if pc["suggestion"].sum() else None
        st.caption(
            f"Mentions, so one review can count at several stages. Suggestions aren't shown: {int(pc['suggestion'].sum())} "
            f"in all{f', most at {nice_stage(top_sug)}' if top_sug else ''}. Read with care: people tend to praise outcomes "
            "(accurate measurements, faster quotes) and complain about process, so a smooth login or upload rarely gets "
            "a review."
        )

        st.markdown("**Who is complaining, by stage**")
        who = comp.assign(who=comp["user_type"].map(WHO_NAMES).replace({"reviewer": "not said"}))
        tbl = who.pivot_table(index="stage", columns="who", values="review_id", aggfunc="nunique", fill_value=0)
        tbl = tbl.reindex(stages_shown).dropna(how="all").fillna(0).astype(int)
        tbl.index = [nice_stage(s) for s in tbl.index]
        st.dataframe(tbl, width="stretch")
        all_comp = mentions_long(labeled_all)
        all_comp = all_comp[all_comp["sentiment"] == "complaint"].drop_duplicates("review_id")
        st.caption(
            f"Of {len(all_comp)} reviews with a complaint {since_txt} before any filter, "
            f"{int(all_comp['insurance_side'].astype(bool).sum())} come from the insurance side, and "
            f"{int((all_comp['user_type'] == 'other_unclear').sum())} don't say who they are."
        )

# ---------------- Review explorer ----------------
with tabs[4]:
    st.markdown("## Review explorer")
    st.caption("Every labeled mention, with the exact words behind it. Filter by sentiment, stage, problem type or who "
               "wrote it, or search the text.")
    if ment.empty:
        st.write("No labels yet.")
    else:
        g = ment.copy()
        f1, f2, f3, f4 = st.columns(4)
        sent = f1.multiselect("Sentiment", SENTIMENTS, default=["complaint"])
        stg = f2.multiselect("Stage", STAGES, format_func=nice_stage)
        tg = f3.multiselect("Tag (complaints)", TAGS, format_func=nice_tag)
        who = f4.multiselect("Who", sorted(g["user_type"].unique()))
        text_q = st.text_input("Search the review text", placeholder="e.g. upload, fee, EagleView")
        if sent:
            g = g[g["sentiment"].isin(sent)]
        if stg:
            g = g[g["stage"].isin(stg)]
        if tg:
            g = g[g["tags"].apply(lambda ts: any(t in ts for t in tg))]
        if who:
            g = g[g["user_type"].isin(who)]
        if text_q:
            g = g[(g["title"] + " " + g["text"]).str.contains(text_q, case=False, regex=False)]
        g = g.sort_values("date", ascending=False)
        st.caption(f"{len(g)} mentions from {g['review_id'].nunique()} reviews match.")
        st.dataframe(pd.DataFrame({
            "date": g["date"].dt.date, "store": g["source"].map(STORE_NAMES), "stars": g["rating"],
            "who": g["user_type"], "sent by": g["invited_by"], "stage": g["stage"].map(nice_stage),
            "sentiment": g["sentiment"], "tags": g["tags"].apply(lambda ts: ", ".join(nice_tag(t) for t in ts)),
            "what they said": g["quote"], "review": g["title"] + " — " + g["text"],
        }), width="stretch", hide_index=True, height=520, column_config={"review": st.column_config.TextColumn(width="large")})

# ---------------- Method & validation ----------------
with tabs[5]:
    st.markdown("## Method and validation")
    st.subheader("Reading the Overview")
    for note in overview_notes():
        st.markdown(note)
    st.subheader("How the labels were made")
    if info:
        st.markdown(
            f"- **Labeler:** a large language model reading each review against a written codebook. Showing "
            f"**{info['pass_name']}**, codebook version `{info['codebook_version']}`, prompt `{info['prompt_version']}`; "
            f"{info['n_labeled']} reviews labeled.\n"
            "- **Mentions:** each review is split into one mention per stage and sentiment (complaint, praise or "
            "suggestion), so a review can count at several stages.\n"
            "- **Two independent passes:** two different models labeled the same reviews separately, with the same "
            "codebook. Where they agree is a consistency check, not proof: both can make the same mistake.\n"
            "- **Evidence rule:** every mention needs an exact quote from the review; mentions whose quotes don't match "
            "the text word for word are dropped.\n"
            "- **Categories:** two independent AI read-throughs of the reviews since 2023 each proposed categories; they "
            "were merged into stages that follow Hover's own workflow, which I reviewed and approved."
        )
        lab = df_all[df_all["labeled"]] if "labeled" in df_all else df_all.iloc[0:0]
        if len(lab):
            ok, bad = int(lab["quotes_ok"].sum()), int(lab["quotes_failed"].sum())
            st.markdown(f"- **Quote check:** {ok} mentions had quotes that matched the review; {bad} didn't and were dropped.")
    st.subheader("Agreement between the two passes")
    if PASS_AGREEMENT.exists():
        ag = json.loads(PASS_AGREEMENT.read_text())
        if "stages" in ag:
            st.caption(f"{ag['n']} reviews labeled by both passes. Kappa corrects for chance agreement: 1 is perfect, 0 is "
                       "chance. The interval is a bootstrap 95% range.")
            f = pd.DataFrame(ag["fields"]).T.reindex(columns=["n", "agreement", "kappa", "kappa_lo", "kappa_hi"])
            st.dataframe(f.astype(float).round(2), width="stretch")
            t = pd.DataFrame(ag["stages"])
            t["stage"] = t["stage"].map(nice_stage)
            t = t[["stage", "complaint_a_n", "complaint_b_n", "complaint_kappa", "praise_a_n", "praise_b_n",
                   "praise_kappa", "suggestion_a_n", "suggestion_b_n", "suggestion_kappa"]]
            t.columns = ["stage", "complaints A", "complaints B", "complaint kappa", "praise A", "praise B",
                         "praise kappa", "suggestions A", "suggestions B", "suggestion kappa"]
            st.dataframe(t.round(2), width="stretch", hide_index=True)
        else:
            st.write("Out of date for this codebook: run `uv run python -m hover_reviews.pass_agreement`.")
    else:
        st.write("Not computed yet: run `uv run python -m hover_reviews.pass_agreement`.")
    st.subheader("Caveats")
    st.markdown(
        "- Written reviews are self-selected and skew negative; they show what goes wrong, not how often.\n"
        "- Apple's feed returns only the most recent few hundred US reviews; Google Play's export has only written "
        "reviews in English. Star-only ratings can't be seen or labeled.\n"
        "- Many reviewers don't say who they are, so filters by user type undercount.\n"
        "- App reviewers are mostly people capturing homes; estimating and web-app feedback is under-represented."
    )
    with st.expander("The codebook"):
        st.markdown(codebook_text())
