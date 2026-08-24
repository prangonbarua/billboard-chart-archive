#!/usr/bin/env python3
"""Bring every updatable chart CSV forward to a target week.

The repo has no key -> Billboard-slug map; the plan JSON run_batch_backfill.py
expects was never committed. This rebuilds it and PROVES each entry rather
than trusting a name match, because a mis-mapped slug writes another chart's
rows into a CSV and no row count catches that.

The proof: refetch a week the CSV already holds and compare the (rank, song)
ordering. A wrong slug returns a different chart and fails. This also catches
Billboard's clamp -- an out-of-range date is served as the boundary week's
rankings under the date asked for -- because a clamped response will not match
the known week either.

A chart whose slug cannot be proven is SKIPPED and reported, never guessed at.
"""
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

from fast_billboard_scraper import scrape_billboard_chart  # noqa: E402

TARGET = sys.argv[1] if len(sys.argv) > 1 else '2026-08-22'
ONLY = sys.argv[2] if len(sys.argv) > 2 else None


def registry():
    """key -> (label, csv) for every registered chart, read without importing app."""
    import ast
    tree = ast.parse((ROOT / 'app.py').read_text())

    def assign(name):
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == name:
                return node.value
        raise KeyError(name)

    # CHARTS entries do not name their CSV: they are loaded into module globals
    # and CHART_DATA maps the key to that global. Two regexes join the pair.
    import re
    src = (ROOT / 'app.py').read_text()
    global_csv = dict(re.findall(
        r"(\w+),\s*\w+\s*=\s*_load_global_chart\('([^']+\.csv)'\)", src))
    for name in re.findall(r"(\w+),\s*\w+\s*=\s*_load_hot100[^\n]*", src):
        global_csv.setdefault(name, 'hot100.csv')
    key_global = dict(re.findall(r"'(\w+)':\s*\((\w+),", src))

    out = {}
    charts = assign('CHARTS')
    for k, v in zip(charts.keys, charts.values):
        kw = {a.arg: a.value.value for a in v.keywords}
        out[k.value] = (kw['label'], global_csv.get(key_global.get(k.value, ''), None))
    for k, spec in ast.literal_eval(assign('BATCH_CHARTS')).items():
        out[k] = (spec[0], spec[4])
    # Hits of the World entries are appended to BATCH_CHARTS at import time.
    for stem, country in ast.literal_eval(assign('HOTW_COUNTRIES')):
        key = stem.replace('-', '_') + '_hotw'
        out[key] = (f'{country} Songs', f"{stem.replace('-', '_')}_hotw.csv")
    return out


# The two oldest charts predate _load_global_chart and are loaded by their own
# functions with a filename fallback list, so no regex recovers them.
HAND_LOADED = {'top100': 'hot100.csv', 'albums200': 'billboard200.csv'}


def csv_path(key, declared):
    for name in ([HAND_LOADED.get(key), declared] if True else []) + [f'{key}.csv']:
        if not name:
            continue
        p = ROOT / 'data' / name
        if p.exists():
            return p
    return None


def read_csv(path):
    with open(path, newline='') as fh:
        return list(csv.DictReader(fh)), csv.DictReader(open(path)).fieldnames


def weeks_in(rows):
    return sorted({(r.get('Date') or '')[:10] for r in rows if r.get('Date')})


def candidates(key, label):
    """Slug guesses, most likely first. Each is PROVEN before use."""
    import re
    seen, out = set(), []

    def add(s):
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    slug = re.sub(r'[^a-z0-9]+', '-', label.lower().replace('&', ' and ')).strip('-')
    slug = slug.replace('the-', '', 1) if slug.startswith('the-') else slug
    add(slug)
    add(slug.replace('-and-', '-'))
    add(key.replace('_', '-'))
    add('hot-' + slug)
    add(slug.replace('top-', ''))
    add(slug + '-songs')
    # Slugs already known to the scraper are the strongest source available.
    scraper = (ROOT / 'scripts' / 'fast_billboard_scraper.py').read_text()
    toks = set(re.findall(r"'([a-z0-9][a-z0-9-]{3,})':\s*\d+", scraper))
    stem = slug.split('-')[0]
    for t in sorted(toks):
        if stem and stem in t:
            add(t)
    return out[:10]


def prove(slug, known_week, known_rows):
    """True if `slug` at `known_week` reproduces what the CSV already holds."""
    got = scrape_billboard_chart(slug, known_week)
    if not got:
        return False
    mine = [(str(r['Rank']), str(r['Song']).casefold().strip()) for r in known_rows][:5]
    theirs = [(str(r['Rank']), str(r['Song']).casefold().strip()) for r in got][:5]
    return len(mine) >= 3 and mine == theirs


def main():
    reg = registry()
    plan, skipped, updated, current, failed = {}, [], [], [], []

    for key, (label, declared) in sorted(reg.items()):
        if ONLY and key != ONLY:
            continue
        path = csv_path(key, declared)
        if path is None:
            skipped.append((key, 'no csv'))
            continue
        rows, fields = read_csv(path)
        if not rows:
            skipped.append((key, 'empty csv'))
            continue
        wk = weeks_in(rows)
        last = wk[-1]
        if last >= TARGET:
            current.append(key)
            continue

        anchor = last
        anchor_rows = sorted((r for r in rows if (r.get('Date') or '')[:10] == anchor),
                             key=lambda r: int(float(r['Rank'])))
        good = None
        for slug in candidates(key, label):
            try:
                if prove(slug, anchor, anchor_rows):
                    good = slug
                    break
            except Exception:
                pass
            time.sleep(0.4)
        if not good:
            skipped.append((key, f'slug unproven (last={last})'))
            print(f'SKIP  {key:34s} slug unproven', flush=True)
            continue

        plan[good] = {'key': key, 'csv': path.name, 'anchor': anchor}

        # Fetch every published week after the anchor, up to the target.
        added, misses = 0, 0
        cur = anchor
        while cur < TARGET and misses < 3:
            import datetime as dt
            cur = (dt.date.fromisoformat(cur) + dt.timedelta(days=7)).isoformat()
            if cur > TARGET:
                break
            try:
                got = scrape_billboard_chart(good, cur)
            except Exception:
                got = None
            if not got:
                misses += 1
                continue
            # Clamp guard: identical ordering to the previous known week means
            # Billboard served the boundary week under this date.
            prev = sorted((r for r in rows if (r.get('Date') or '')[:10] == anchor),
                          key=lambda r: int(float(r['Rank'])))
            a = [(str(r['Rank']), str(r['Song']).casefold()) for r in prev]
            b = [(str(r['Rank']), str(r['Song']).casefold()) for r in got]
            if a and a == b:
                misses += 1
                print(f'CLAMP {key:34s} {cur} identical to {anchor}', flush=True)
                continue
            with open(path, 'a', newline='') as fh:
                w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
                for r in got:
                    w.writerow({**{f: '' for f in fields}, **r, 'Date': cur})
            added += len(got)
            anchor = cur
            rows.extend([{**r, 'Date': cur} for r in got])
            time.sleep(0.5)

        if added:
            updated.append((key, good, anchor, added))
            print(f'OK    {key:34s} {good:34s} -> {anchor} (+{added} rows)', flush=True)
        else:
            failed.append((key, good, last))
            print(f'NONE  {key:34s} {good:34s} still {last}', flush=True)

    (ROOT / 'scripts' / 'chart_plan.json').write_text(json.dumps(plan, indent=2, sort_keys=True))
    print('\n==== SUMMARY ====')
    print(f'already current : {len(current)}')
    print(f'updated         : {len(updated)}')
    print(f'no new week     : {len(failed)}')
    print(f'skipped         : {len(skipped)}')
    for k, why in skipped:
        print(f'   SKIP {k}: {why}')
    print(f'proven slugs written to scripts/chart_plan.json: {len(plan)}')


if __name__ == '__main__':
    main()
