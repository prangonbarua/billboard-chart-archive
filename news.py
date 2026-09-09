"""Facts about the newest chart week, read straight off the loaded CSVs.

Nothing here is written by hand or inferred. Every sentence the news page
prints traces back to two rows of a CSV: the week being reported and the week
before it. That constraint is deliberate. This site's whole failure mode is
plausible-looking data that nobody sourced, so a page whose job is to make
claims about the charts gets to make only claims it can point at.

Two things it deliberately does NOT say:

  * "debut". Telling a first-ever appearance from a re-entry needs the title's
    whole history on that chart, which is a full scan per chart. What is cheap
    and true is "was not on this chart last week", so that is what it claims.
  * anything about a chart missing either week. A chart that skipped the week,
    or launched after it, is left out rather than guessed at.
"""
import pandas as pd

# Rank improvement below this is not news, it is ordinary chart drift.
_MIN_CLIMB = 20
_TOP_N = 6


def _week_frame(df, dt, day):
    """The rows of one chart for one week, ranked, or None."""
    rows = df[dt == day]
    if not len(rows):
        return None
    rows = rows.dropna(subset=['Rank'])
    return rows if len(rows) else None


def _pair(row):
    return (str(row['Song']).strip(), str(row['Artist']).strip())


def weekly_news(chart_data, chart_dt, charts):
    """Everything the news page prints, for the most recent week on record.

    `week` is the newest date ANY chart carries. Charts that do not have that
    week are skipped, not backfilled to their own latest week — mixing weeks
    under one date is how this project has fabricated data before.
    """
    latest = None
    for key, dt in chart_dt.items():
        if key not in charts:
            continue
        top = dt.max()
        if pd.notna(top) and (latest is None or top > latest):
            latest = top
    if latest is None:
        return None

    new_ones, climbs, entries = [], [], []
    covered = 0

    for key, meta in charts.items():
        df, _ = chart_data.get(key, (None, None))
        dt = chart_dt.get(key)
        if df is None or dt is None:
            continue
        now = _week_frame(df, dt, latest)
        if now is None:
            continue
        covered += 1

        # The week before is this chart's own previous week, not latest minus
        # seven days. Charts skip weeks, and a chart that skipped would
        # otherwise silently compare against nothing.
        earlier = dt[dt < latest]
        if not len(earlier):
            continue
        prev = _week_frame(df, dt, earlier.max())
        if prev is None:
            continue

        label = meta.get('label', key)
        prev_rank = {_pair(r): int(r['Rank']) for _, r in prev.iterrows()}

        top_now = now[now['Rank'] == 1]
        top_prev = prev[prev['Rank'] == 1]
        if len(top_now) and len(top_prev):
            a, b = _pair(top_now.iloc[0]), _pair(top_prev.iloc[0])
            if a != b:
                new_ones.append(dict(chart=label, kind=meta.get('kind'),
                                     song=a[0], artist=a[1],
                                     was=b[0], was_artist=b[1],
                                     last_rank=prev_rank.get(a)))

        for _, r in now.iterrows():
            pair = _pair(r)
            rank = int(r['Rank'])
            was = prev_rank.get(pair)
            if was is None:
                entries.append(dict(chart=label, kind=meta.get('kind'),
                                    song=pair[0], artist=pair[1], rank=rank))
            elif was - rank >= _MIN_CLIMB:
                climbs.append(dict(chart=label, kind=meta.get('kind'),
                                   song=pair[0], artist=pair[1],
                                   rank=rank, was=was, gain=was - rank))

    climbs.sort(key=lambda c: -c['gain'])
    entries.sort(key=lambda e: e['rank'])
    new_ones.sort(key=lambda n: n['chart'])

    return dict(
        week=latest.strftime('%Y-%m-%d'),
        week_long=latest.strftime('%B %-d, %Y'),
        charts_covered=covered,
        new_ones=new_ones[:_TOP_N],
        total_new_ones=len(new_ones),
        climbs=climbs[:_TOP_N],
        entries=entries[:_TOP_N],
        total_climbs=len(climbs),
        total_entries=len(entries),
        min_climb=_MIN_CLIMB,
    )


def reign(df, dt, chart_key=None):
    """How many consecutive weeks the current #1 has held the top spot.

    Counts backwards through the chart's own weeks and stops at the first one
    that is either a different title or a week the chart did not publish, so a
    gap in the archive ends a run rather than being counted through.
    """
    if df is None or dt is None or not len(df):
        return None
    ones = df[df['Rank'] == 1].copy()
    if not len(ones):
        return None
    ones['_dt'] = dt.reindex(ones.index)
    ones = ones.dropna(subset=['_dt']).sort_values('_dt', ascending=False)
    if not len(ones):
        return None
    head = ones.iloc[0]
    title = _pair(head)
    weeks = 0
    for _, r in ones.iterrows():
        if _pair(r) != title:
            break
        weeks += 1
    return dict(song=title[0], artist=title[1], weeks=weeks,
                since=ones.iloc[weeks - 1]['_dt'].strftime('%Y-%m-%d'))
