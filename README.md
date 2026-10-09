# Hover app reviews: where complaints land

An independent analysis of public App Store and Google Play reviews of the Hover app ("Measure Design Estimate"). Not affiliated with Hover Inc.

**Dashboard:** https://hover-reviews-dashboard.streamlit.app

## What it does

Each review is split into mentions: every stage of the journey it complains about, praises or makes a suggestion on counts separately, with the exact words that show it. The stages follow Hover's own workflow: getting in, capture, model delivery, measurements, design, estimate and proposal, plus paying. An AI labeler did the splitting against the written policy in `codebook.md`, two different models labeled every review independently, and a mention only counts if its quote matches the review word for word. `data/pass_agreement.json` has the agreement between the two passes.

## The data

- `data/reviews.csv`: 807 written reviews, 427 from the US App Store (Apple's public review feed) and 380 in English from Google Play. Reviews since January 1, 2023 are labeled.
- Reviewer names are not included. Two reviews that put a street address, a job number or the reviewer's own name in their text have those details masked.
- `data/labels/labels.jsonl`: the labels, with their quote checks.

## Caveats

Written reviews skew negative, so they show what goes wrong, not how often. App reviewers are mostly people capturing homes in the field, so estimating and web-app feedback is under-represented, and reviews don't say which plan anyone is on.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```
