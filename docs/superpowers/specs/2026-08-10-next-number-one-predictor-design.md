# Next #1 predictor — design

Written 2026-08-10. Predicts next week's Hot 100 #1 from this archive.

## Why not Luminate directly

Luminate (formerly Nielsen SoundScan / MRC Data) licenses consumption data
commercially. There is no public or free API. Billboard's charts ARE derived
from Luminate, so this archive is that data one aggregation step removed, at
weekly granularity. **Be honest in the UI: this predicts chart position, which
is a lagging proxy for the consumption data underneath.** If a licensed
Luminate feed ever becomes available, it replaces the feature source, not the
design.

## The two numbers that constrain everything

Measured across all 3,548 Hot 100 week-to-week transitions, 1958-08-09 to
2026-08-08:

| fact | value |
|---|---|
| incumbent #1 holds next week | **62.3%** |
| next #1 was in this week's top 5 | 93.5% |
| next #1 was in this week's top 20 | 96.5% |
| next #1 was NOT on the chart at all | 2.6% |

**62.3% is the baseline to beat.** "Predict no change" scores that with no
model at all, so any accuracy at or below it is worthless. **~97.4% is the
ceiling** — the 2.6% that debut straight to #1 are unreachable from chart data.
The model is competing for a ~35 point band, not a 0-100 one.

## Target and candidates

For each week W, take each song in that week's **top 20** and label it 1 if it
is #1 in week W+1. Binary classification; predict argmax probability. One model
covers both "incumbent holds" and "challenger takes over".

Top 20 captures 96.5%. The full 100 adds 0.9% for 5x the rows.

## Features

**All derived by walking the archive week to week. Never read the stored
`Last Week` or `Peak Position` columns** — they are corrupt in pre-2025 rows,
where a debut was written as `Last Week == Rank` and `Peak Position == 1`.
`app.py` already recomputes them for the same reason.

- current rank, and log rank (1->2 matters far more than 50->51)
- rank change over 1, 2 and 3 weeks
- weeks on chart, counted from actual appearances
- peak position so far, recomputed
- `is_incumbent`, and consecutive weeks held at #1
- the incumbent's own momentum — a #1 that arrived on a rising trend behaves
  differently from one plateauing
- debut flag

## Training

**Window: 1990 onward** (~1,850 weeks). Chart dynamics changed enormously
between 1960s turnover and the streaming era's long #1 runs; 1962 is close to
irrelevant for predicting 2026. Prefer less data that matches the target
distribution.

**Split chronologically, never shuffled** — train 1990-2015, validate
2016-2020, test 2021-present. Random splitting leaks the future into the past
through adjacent weeks and produces a fake accuracy number.

**Logistic regression, trained offline.** Train with sklearn locally, commit
coefficients to `data/predictor_weights.json`, do inference at request time in
plain pandas/numpy. sklearn is NOT in `requirements.txt` and must not be added
— Railway builds from that file, and pickled models break across sklearn
versions. Coefficients stay human-readable, so the page can explain a
prediction in a sentence.

## Evaluation — report both, on held-out data only

1. Top-1 accuracy vs the 62.3% baseline
2. **Accuracy restricted to weeks where the #1 actually changed**

The second number is the real one. A model can score 62% by always saying "no
change" and be useless. **If the model does not beat 62.3% on the test window,
say so plainly rather than shipping it behind a flattering metric.**

## Components

| file | purpose |
|---|---|
| `predictor.py` | feature engineering + inference; shared by script and app |
| `scripts/train_predictor.py` | offline training, writes the weights JSON |
| `data/predictor_weights.json` | committed coefficients + backtest metrics |
| `app.py` | `/predict` route |
| `templates/predict.html` | prediction + runners-up + accuracy record |
| `tests/test_predictor.py` | see below |

Feature engineering lives in `predictor.py` and is imported by both the
trainer and the app, so training and serving cannot drift apart — the classic
way this kind of model silently breaks.

## Error handling

- Weights file missing or unparseable -> flash and redirect to `top100`,
  matching how every other chart route handles absent data
- A song with less than 3 weeks of history -> features degrade to sentinels
  rather than dropping the candidate
- Current week has no chart data yet -> show the last complete week and label
  it as such

## The accuracy record is computed, not stored

Railway's filesystem is ephemeral, so per-week predictions cannot be logged to
disk and accumulated. The page shows the **backtest** record over held-out
history, recomputed at startup. Honest and stateless. Storing a live prediction
log needs a real datastore and is out of scope.

## Testing

- Feature derivation against a hand-built fixture with known ranks — including
  a debut, a re-entry, and a song whose stored `Last Week` is deliberately
  wrong, proving features come from the archive and not the column
- Chronological split contains no overlap and no future leakage
- Inference from committed weights reproduces the trainer's own probability
  for the same row (train/serve parity)
- `/predict` returns 200 and degrades correctly when weights are absent
- Baseline comparison is computed, not hardcoded, so it tracks the data

## Out of scope

Other charts, Discord delivery, a stored prediction log, and any model beyond
logistic regression. Get one chart honest first.
