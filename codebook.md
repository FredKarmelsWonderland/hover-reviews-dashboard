# Codebook v3

The labeling policy for Hover app reviews. The AI labeler reads this file verbatim. Changing this file changes the codebook version and invalidates cached labels.

v3 (October 9, 2026) splits each review into **mentions**. v2 gave each review one stage and one overall tone, so a review that praised the design tool and complained about uploads could only count once. Now every part of the journey a review talks about counts separately, with its own sentiment and its own exact quote. The stages follow Hover's own workflow (capture, measure, design, estimate, propose).

## General rules

- **Label what the review says, not what you infer.** If the reviewer doesn't talk about a stage, don't create a mention for it.
- **One mention per stage and sentiment.** If a review complains about uploads twice, that's one complaint mention at `model_delivery`. If it praises the design tool and complains about it, that's two mentions at `design`: one praise, one complaint.
- **Evidence is required.** Every mention needs a quote copied exactly from the review (title or text): the few words that show the stage and the sentiment. No paraphrasing, no fixed typos. A mention without an exact quote doesn't count.
- **Judge from the text, not the star rating.**

## Stages

| Stage | What it covers | Not this |
| --- | --- | --- |
| `getting_in` | Before any capture: the app won't open or hangs on loading, login, password reset, creating an account, having to sign up before seeing anything, linking to an insurer's or contractor's request, not knowing what to do first | Crashes later in the app (use the stage where the crash happened) |
| `capture` | Taking the photos, scan or video on site: camera controls, no way to upload photos already on the phone, required angles or corner shots, tight lots, trees, townhomes, roofs that can't be photographed, interior scans while scanning, battery or overheating during capture | Photos lost or stuck after submitting (`model_delivery`) |
| `model_delivery` | After submitting, until the model or report arrives: uploading, stuck on "uploading" or "evaluating," lost photos or projects, needing a connection, jobs that fail or are rejected, being asked to retake photos, waiting hours or days for results | Wrong numbers in a delivered model (`measurements`) |
| `measurements` | The delivered measurements, square footage, floor plan, report or 3D model, and whether they're right: accuracy, wrong numbers, missing walls or rooms, consequences of a wrong number (a premium change, a short material order) | Colors or materials in the design tool (`design`) |
| `design` | The 3D design and visualization tool: trying siding, roofing, colors and products, the product catalog, how realistic renderings look, editing individual elements | Measurement accuracy (`measurements`) |
| `estimate_proposal` | Using the output to sell or do the job: material lists, ordering, quotes, Hover's Estimates, proposals, exports, integrations (CRMs, Xactimate, Chief Architect), saving time on bids or claims | What Hover itself costs (`paying`) |
| `paying` | What Hover costs: subscriptions, per-job fees, "complex" surcharges, unexpected charges, refunds, prepaid packages, paid exports, sales tactics | Pricing a job for a customer (`estimate_proposal`) |
| `general` | The whole app or company, with no stage: "great app," "garbage," general praise for the technology, support or privacy with no stage | Use only when no stage fits |

## Sentiment (one per mention)

- `complaint`: reports a problem, failure, frustration, wrong result or cost.
- `praise`: says something works well.
- `suggestion`: asks for something or wishes it worked differently ("would be nice," "I wish," "please add") without reporting a problem or a bad experience. If the reviewer also says it caused a problem, it's a `complaint`.

## Tags (complaint mentions only, any number)

What kind of problem it is. Use an empty list for praise and suggestions.

| Tag | What it covers |
| --- | --- |
| `crash_bug` | Crashes, freezes, blank screens, glitches, won't load |
| `lost_work` | Photos, designs, projects or measurements lost or vanished; having to redo work because of it |
| `wrong_output` | A measurement, model, floor plan or rendering that's wrong or incomplete |
| `waiting` | Slow processing, long turnaround, a slow app |
| `cant_do_it` | The app can't do something the reviewer needed: a missing feature, product, option or property type it can't handle |
| `hard_to_use` | Confusing flow, unclear instructions, clunky navigation |
| `update_worse` | A new version or redesign made things worse; "bring back the old version" |
| `support` | Customer service, help chat, sales reps or account managers |
| `cost` | Price, fees, charges or value for money |

## Review-level fields

### Stance (the review overall)

- `gripe`: mainly a complaint.
- `praise`: mainly positive.
- `mixed`: a real complaint and real praise.
- `neutral`: neither (a question or a description).

### Severity (0 if the review has no complaint mention)

1. **Annoyance:** cosmetic, a minor inconvenience.
2. **Real friction:** wasted time, had to retry, needed a workaround.
3. **Blocked or lost something:** couldn't finish, lost work or photos, lost money, lost a customer or a job, gave up on the product.

### User type

- `contractor`: a roofer, siding or remodeling contractor, estimator, builder or sales rep.
- `adjuster`: an insurance adjuster or appraiser.
- `homeowner`: a homeowner or resident.
- `other_unclear`: anyone else, or not stated.

Use what the reviewer says about themselves or clearly implies ("my customers" means contractor). If the review doesn't say, use `other_unclear`; don't guess.

### Invited by

Who asked the reviewer to use Hover:

- `insurer`: an insurance company.
- `contractor`: a contractor or company giving a bid.
- `self_or_none`: chose it themselves, or no one is mentioned.
- `unclear`.

### Competitors

List any other products named: EagleView, Roofr, GAF QuickMeasure, CompanyCam, Xactimate, DocuSketch and so on. Use an empty list if none.
