#!/usr/bin/env python3
"""Prove Billboard slugs for the charts refresh_to_week.py could not resolve.

Its candidates() generator derives slugs from the label, which fails whenever
Billboard's URL is not a slugified label -- 'Hot R&B/Hip-Hop Songs' lives at
r-b-hip-hop-songs, not hot-r-and-b-hip-hop-songs. This supplies hand-written
candidates for exactly those charts and PROVES each one the same way: refetch a
week the CSV already holds and compare the (rank, song) ordering. Nothing is
guessed; an unproven slug stays unproven.

Proven slugs are merged into scripts/chart_plan.json so refresh_to_week.py picks
them up on its next run.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

from refresh_to_week import registry, csv_path, read_csv, weeks_in, prove  # noqa: E402

# Hand-written candidates for the 13 skips. Billboard is inconsistent about how
# it renders & and / in a URL, which is the whole reason the derived slugs miss.
EXTRA = {
    'adult_alternative':  ['adult-alternative-songs', 'triple-a', 'adult-alternative'],
    'afrobeats_songs':    ['afrobeats-songs', 'us-afrobeats-songs', 'hot-afrobeats-songs'],
    'christian':          ['hot-christian-songs', 'christian-songs'],
    'dance_albums':       ['dance-electronic-albums', 'top-dance-electronic-albums',
                           'dance-albums'],
    'dance_electronic':   ['hot-dance-electronic-songs', 'dance-electronic-songs'],
    'gospel':             ['hot-gospel-songs', 'gospel-songs'],
    'hot_rnb_songs':      ['hot-r-and-b-songs', 'r-b-songs', 'hot-r-b-songs'],
    'japan_hot100':       ['japan-hot-100', 'japan-hot-100-songs'],
    'rap_songs':          ['hot-rap-songs', 'rap-song', 'rap-songs'],
    'rnb_hiphop_albums':  ['r-b-hip-hop-albums', 'top-r-b-hip-hop-albums',
                           'r-and-b-hip-hop-albums'],
    'rnb_songs':          ['r-b-hip-hop-songs', 'hot-r-and-b-hip-hop-songs',
                           'r-and-b-hip-hop-songs'],
    'smooth_jazz_airplay': ['smooth-jazz-airplay', 'smooth-jazz-songs'],
    # world_singles is deliberately absent. It is MediaTraffic, not Billboard --
    # no Billboard slug exists and scripts/backfill_mediatraffic.py owns it.
}

PLAN = ROOT / 'scripts' / 'chart_plan.json'


def main():
    reg = registry()
    proven, failed = {}, []

    for key, slugs in EXTRA.items():
        meta = reg.get(key)
        if meta is None:
            failed.append((key, 'not in registry'))
            print(f'SKIP  {key:22s} not in registry', flush=True)
            continue

        # registry() yields (label, csv) tuples, not dicts.
        _label, declared_csv = meta
        path = csv_path(key, declared_csv)
        # read_csv returns (rows, fieldnames).
        rows, _fields = read_csv(path)
        if not rows:
            failed.append((key, 'no CSV rows to anchor against'))
            print(f'SKIP  {key:22s} no CSV rows', flush=True)
            continue

        weeks = weeks_in(rows)
        anchor = max(weeks)
        anchor_rows = [r for r in rows if r.get('Date') == anchor]

        hit = None
        for slug in slugs:
            try:
                if prove(slug, anchor, anchor_rows):
                    hit = slug
                    break
                print(f'      {key:22s} {slug} -> no match', flush=True)
            except Exception as exc:
                print(f'      {key:22s} {slug} -> error {exc}', flush=True)

        if hit:
            proven[key] = hit
            print(f'PROVEN {key:22s} {hit}  (anchor {anchor})', flush=True)
        else:
            failed.append((key, 'all candidates unproven'))
            print(f'FAIL  {key:22s} all candidates unproven', flush=True)

    if proven:
        plan = {}
        if PLAN.exists():
            try:
                plan = json.loads(PLAN.read_text())
            except Exception:
                plan = {}
        plan.update(proven)
        PLAN.write_text(json.dumps(plan, indent=2, sort_keys=True))
        print(f'\nmerged {len(proven)} proven slugs into {PLAN}', flush=True)

    print(f'\nproven: {len(proven)}   failed: {len(failed)}')
    for key, why in failed:
        print(f'   {key}: {why}')


if __name__ == '__main__':
    main()
