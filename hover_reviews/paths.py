"""File locations, in one place."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW_APPSTORE = DATA / "raw" / "appstore"
APPSTORE_META = DATA / "raw" / "appstore_meta.json"
MANUAL_GOOGLE_PLAY = DATA / "google_play_manual.csv"
REVIEWS = DATA / "reviews.csv"
LABELS = DATA / "labels" / "labels.jsonl"
HAND_LABELS = DATA / "hand_labels.csv"
AGREEMENT = DATA / "agreement.json"
CODEBOOK = ROOT / "codebook.md"
PASS_AGREEMENT = DATA / "pass_agreement.json"
DISAGREEMENTS = DATA / "disagreements.csv"
