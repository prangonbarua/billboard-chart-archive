#!/usr/bin/env python3
"""Bring every updatable chart CSV forward to a target week.

    refresh_to_week.py [TARGET] [KEY[,KEY...]] [--fresh]

TARGET defaults to the Saturday on or after today, which is as far as any
chart can be dated; charts that have not published that week simply stop at
their latest one. KEY limits the run to one chart or a comma-separated group.

The repo has no committed key -> Billboard-slug map, so each run PROVES the
slug it uses rather than trusting a name match, because a mis-mapped slug
writes another chart's rows into a CSV and no row count catches that.

The proof: refetch a week the CSV already holds and compare the (rank, song)
ordering. A wrong slug returns a different chart and fails. This also catches
Billboard's clamp -- an out-of-range date is served as the boundary week's
rankings under the date asked for -- because a clamped response will not match
the known week either.

A chart whose slug cannot be proven is SKIPPED and reported, never guessed at.

Safe to rerun and to kill:

- Idempotent. A chart already at TARGET is not fetched, and a week the CSV
  already holds is never appended again. Each week is written in one append,
  so a kill leaves whole weeks behind, never half of one.
- Resumable. Every finished chart is checkpointed to
  logs/refresh_checkpoints/<TARGET>.json, so a rerun for the same TARGET skips
  charts that are done and retries only the ones that were not. --fresh
  ignores the checkpoint.
- Never writes scripts/known_slugs.json. It is read once and hashed; if its
  bytes differ at the end of the run, the run fails. chart_plan.json is
  MERGED per chart, not rewritten, so a one-chart run no longer wipes the
  slugs every other chart proved.
- Never extends a chart listed in scripts/frozen_charts.json.
"""
import csv
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))

def default_target(today=None):
    today = today or dt.date.today()
    return (today + dt.timedelta(days=(5 - today.weekday()) % 7)).isoformat()


def registry(root=ROOT):
    """key -> (label, csv) for every registered chart, read without importing app."""
    import ast
    src = (root / 'app.py').read_text()
    tree = ast.parse(src)

    def assign(name):
        for node in tree.body:
            if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == name:
                return node.value
        raise KeyError(name)

    # CHARTS entries do not name their CSV: they are loaded into module globals
    # and CHART_DATA maps the key to that global. Two regexes join the pair.
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


def csv_path(key, declared, root=ROOT):
    for name in [HAND_LOADED.get(key), declared, f'{key}.csv']:
        if not name:
            continue
        p = root / 'data' / name
        if p.exists():
            return p
    return None


def read_csv(path):
    with open(path, newline='') as fh:
        reader = csv.DictReader(fh)
        return list(reader), reader.fieldnames


def weeks_in(rows):
    return sorted({(r.get('Date') or '')[:10] for r in rows if r.get('Date')})


def _json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def known_slugs(root=ROOT):
    """Hand-proven key -> slug overrides. Read only, never written.

    Separate from chart_plan.json, which is keyed by slug rather than by chart
    key and rewritten by tooling. Overrides live in their own file so nothing
    this script does can lose them.

    These exist because candidates() derives slugs from the label, and Billboard
    does not slugify & and / predictably: 'Hot R&B/Hip-Hop Songs' is served at
    r-b-hip-hop-songs, and 'Hot Rap Songs' at the singular rap-song. Each entry
    here was proven by refetching a known week, same as any derived candidate.
    """
    return _json(root / 'scripts' / 'known_slugs.json', {})


def frozen_charts(root=ROOT):
    data = _json(root / 'scripts' / 'frozen_charts.json', {})
    return {k: v for k, v in data.items() if not k.startswith('_')}


def planned_slugs(root=ROOT):
    """key -> slug from chart_plan.json, which is keyed by slug."""
    plan = _json(root / 'scripts' / 'chart_plan.json', {})
    return {v['key']: slug for slug, v in plan.items() if isinstance(v, dict) and 'key' in v}


def candidates(key, label, known=None, planned=None, root=ROOT):
    """Slug guesses, most likely first. Each is PROVEN before use."""
    seen, out = set(), []

    def add(s):
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    # Hand-proven override first, then last run's proven slug, so a chart whose
    # URL cannot be derived from its label stops burning fetches on guesses
    # that 404. Still proven, not trusted -- this only changes the ORDER.
    add((known or {}).get(key))
    add((planned or {}).get(key))

    slug = re.sub(r'[^a-z0-9]+', '-', label.lower().replace('&', ' and ')).strip('-')
    slug = slug.replace('the-', '', 1) if slug.startswith('the-') else slug
    add(slug)
    add(slug.replace('-and-', '-'))
    add(key.replace('_', '-'))
    # Hits of the World keeps the suffix on the FULL label: 'Australia Songs'
    # is 'australia-songs-hotw', not 'australia-hotw'. Without this every one
    # of the 38 HOTW charts fails to prove and is skipped.
    if key.endswith('_hotw'):
        add(slug + '-hotw')
        add(slug.replace('-songs', '') + '-songs-hotw')
    add('hot-' + slug)
    add(slug.replace('top-', ''))
    add(slug + '-songs')
    # Slugs already known to the scraper are the strongest source available.
    scraper = root / 'scripts' / 'fast_billboard_scraper.py'
    toks = set(re.findall(r"'([a-z0-9][a-z0-9-]{3,})':\s*\d+", scraper.read_text())) \
        if scraper.exists() else set()
    stem = slug.split('-')[0]
    for t in sorted(toks):
        if stem and stem in t:
            add(t)
    return out[:10]


def _default_scrape(slug, week):
    from fast_billboard_scraper import scrape_billboard_chart
    return scrape_billboard_chart(slug, week)


def prove(slug, known_week, known_rows, scrape=None):
    """True if `slug` at `known_week` reproduces what the CSV already holds."""
    got = (scrape or _default_scrape)(slug, known_week)
    if not got:
        return False
    mine = [(str(r['Rank']), str(r['Song']).casefold().strip()) for r in known_rows][:5]
    theirs = [(str(r['Rank']), str(r['Song']).casefold().strip()) for r in got][:5]
    return len(mine) >= 3 and mine == theirs


def _write_json_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)


def _merge_plan(root, key, slug, csv_name, anchor):
    """Record one chart's proven slug without touching any other chart's entry."""
    path = root / 'scripts' / 'chart_plan.json'
    plan = _json(path, {})
    plan = {s: v for s, v in plan.items() if not (isinstance(v, dict) and v.get('key') == key)}
    plan[slug] = {'key': key, 'csv': csv_name, 'anchor': anchor}
    _write_json_atomic(path, plan)


def _sorted_week(rows, week):
    return sorted((r for r in rows if (r.get('Date') or '')[:10] == week),
                  key=lambda r: int(float(r['Rank'])))


def refresh_chart(key, label, declared, target, known, planned,
                  root=ROOT, scrape=None, sleep=time.sleep):
    """Bring one chart to `target`. Returns (status, detail dict)."""
    scrape = scrape or _default_scrape
    path = csv_path(key, declared, root)
    if path is None:
        return 'skipped', {'why': 'no csv'}
    rows, fields = read_csv(path)
    if not rows:
        return 'skipped', {'why': 'empty csv'}
    last = weeks_in(rows)[-1]
    if last >= target:
        return 'current', {'last': last}

    anchor = last
    anchor_rows = _sorted_week(rows, anchor)
    good = None
    for slug in candidates(key, label, known, planned, root):
        try:
            if prove(slug, anchor, anchor_rows, scrape):
                good = slug
                break
        except Exception:
            pass
        sleep(0.4)
    if not good:
        return 'skipped', {'why': f'slug unproven (last={last})', 'last': last}

    _merge_plan(root, key, good, path.name, anchor)

    # Fetch every published week after the anchor, up to the target.
    added, misses, cur = 0, 0, anchor
    while misses < 3:
        cur = (dt.date.fromisoformat(cur) + dt.timedelta(days=7)).isoformat()
        if cur > target:
            break
        try:
            got = scrape(good, cur)
        except Exception:
            got = None
        if not got:
            misses += 1
            continue
        # Clamp guard: identical ordering to the previous known week means
        # Billboard served the boundary week under this date.
        a = [(str(r['Rank']), str(r['Song']).casefold()) for r in _sorted_week(rows, anchor)]
        b = [(str(r['Rank']), str(r['Song']).casefold()) for r in got]
        if a and a == b:
            misses += 1
            print(f'CLAMP {key:34s} {cur} identical to {anchor}', flush=True)
            continue
        new = [{**{f: '' for f in fields}, **r, 'Date': cur} for r in got]
        with open(path, 'a', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
            w.writerows(new)
        added += len(got)
        anchor = cur
        rows.extend(new)
        sleep(0.5)

    if added:
        return 'updated', {'slug': good, 'from': last, 'last': anchor, 'rows': added}
    return 'none', {'slug': good, 'last': last}


def refresh(target, only=None, fresh=False, root=ROOT, scrape=None, sleep=time.sleep):
    """Refresh every registered chart (or the keys in `only`). Returns results."""
    override = root / 'scripts' / 'known_slugs.json'
    before = hashlib.sha256(override.read_bytes()).hexdigest() if override.exists() else None
    known, planned, frozen = known_slugs(root), planned_slugs(root), frozen_charts(root)

    ckpt_path = root / 'logs' / 'refresh_checkpoints' / f'{target}.json'
    ckpt = {} if fresh else _json(ckpt_path, {})

    results = {}
    for key, (label, declared) in sorted(registry(root).items()):
        if only and key not in only:
            continue
        if key in frozen:
            results[key] = ('frozen', {'kind': frozen[key].get('kind')})
            continue
        # A checkpoint only counts once the chart reached the target. 'none'
        # and 'skipped' are what Billboard's rate limiting looks like from
        # here, and a chart one week short may simply not have published yet,
        # so all three are retried on the next run.
        prior = ckpt.get(key)
        if prior and prior.get('last', '') >= target:
            results[key] = (prior['status'], {**prior, 'resumed': True})
            continue
        status, detail = refresh_chart(key, label, declared, target, known, planned,
                                       root, scrape, sleep)
        results[key] = (status, detail)
        ckpt[key] = {'status': status, **detail}
        _write_json_atomic(ckpt_path, ckpt)
        tag = {'updated': 'OK', 'none': 'NONE', 'skipped': 'SKIP', 'current': 'CUR'}[status]
        print(f'{tag:5s} {key:34s} {json.dumps(detail, sort_keys=True)}', flush=True)

    after = hashlib.sha256(override.read_bytes()).hexdigest() if override.exists() else None
    if before != after:
        raise RuntimeError('scripts/known_slugs.json changed during the refresh run')
    return results


def main(argv):
    fresh = '--fresh' in argv
    args = [a for a in argv if a != '--fresh']
    target = args[0] if args else default_target()
    only = set(args[1].split(',')) if len(args) > 1 else None

    results = refresh(target, only, fresh)
    by = {}
    for key, (status, _) in results.items():
        by.setdefault(status, []).append(key)
    print(f'\n==== SUMMARY (target {target}) ====')
    for status in ('current', 'updated', 'none', 'skipped', 'frozen'):
        print(f'{status:8s}: {len(by.get(status, []))}')
    for key in by.get('skipped', []) + by.get('none', []):
        print(f'   {results[key][0].upper():7s} {key}: {json.dumps(results[key][1], sort_keys=True)}')


if __name__ == '__main__':
    main(sys.argv[1:])
