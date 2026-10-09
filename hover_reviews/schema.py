"""The label schema, matching codebook.md (v3: mentions). The AI returns JSON in this shape."""
import hashlib
from enum import Enum

from pydantic import BaseModel, Field

from .paths import CODEBOOK


class Stage(str, Enum):
    getting_in = "getting_in"
    capture = "capture"
    model_delivery = "model_delivery"
    measurements = "measurements"
    design = "design"
    estimate_proposal = "estimate_proposal"
    paying = "paying"
    general = "general"


class Tag(str, Enum):
    crash_bug = "crash_bug"
    lost_work = "lost_work"
    wrong_output = "wrong_output"
    waiting = "waiting"
    cant_do_it = "cant_do_it"
    hard_to_use = "hard_to_use"
    update_worse = "update_worse"
    support = "support"
    cost = "cost"


class Stance(str, Enum):
    gripe = "gripe"
    praise = "praise"
    mixed = "mixed"
    neutral = "neutral"


class UserType(str, Enum):
    contractor = "contractor"
    adjuster = "adjuster"
    homeowner = "homeowner"
    other_unclear = "other_unclear"


class InvitedBy(str, Enum):
    insurer = "insurer"
    contractor = "contractor"
    self_or_none = "self_or_none"
    unclear = "unclear"


class Sentiment(str, Enum):
    complaint = "complaint"
    praise = "praise"
    suggestion = "suggestion"


class Mention(BaseModel):
    stage: Stage
    sentiment: Sentiment
    quote: str = Field(description="Exact words copied from the review title or text that show this stage and sentiment")
    tags: list[Tag] = Field(description="Problem tags; complaint mentions only, empty otherwise")


class ReviewLabel(BaseModel):
    stance: Stance
    mentions: list[Mention]
    severity: int = Field(description="0 if there is no complaint mention; otherwise 1-3")
    user_type: UserType
    invited_by: InvitedBy
    competitors: list[str]


STAGES = [s.value for s in Stage]  # journey order
TAGS = [t.value for t in Tag]
BEFORE_RESULTS = {"getting_in", "capture", "model_delivery"}  # complaints land before any model or measurements came back
BEFORE_ESTIMATE = BEFORE_RESULTS | {"measurements", "design"}  # paying is off the sequence: fees hit at any point

# Codebook v1 themes, kept only for the parked hand-labeling tools (hand_sample, label_page, agreement).
THEMES_V1 = [
    "capture_upload", "app_stability", "accuracy", "turnaround", "pricing_fees", "estimates", "design_visualization",
    "redesign_ux", "support", "account_access", "property_fit", "insurance_process", "other",
]

# Fixed colors (reference data-viz palette, light slots). Color follows the tag, never its rank.
TAG_COLORS = {
    "crash_bug": "#2a78d6",
    "lost_work": "#eb6834",
    "wrong_output": "#1baf7a",
    "waiting": "#eda100",
    "cant_do_it": "#e87ba4",
    "support": "#008300",
    "update_worse": "#4a3aa7",
    "cost": "#e34948",
}
OTHER_COLOR = "#898781"


def tag_color(tag: str) -> str:
    return TAG_COLORS.get(tag, OTHER_COLOR)


def codebook_text() -> str:
    return CODEBOOK.read_text(encoding="utf-8")


def codebook_version() -> str:
    """Short hash of codebook.md: editing the policy invalidates cached labels."""
    return hashlib.sha256(codebook_text().encode("utf-8")).hexdigest()[:10]
