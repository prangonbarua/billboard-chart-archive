#!/usr/bin/env python3
"""Drive scripts/backfill_chart.py over a batch of charts, N at a time.

Reads a JSON plan of {slug: {csv, first_week, ...}} and runs one backfill
subprocess per chart, capped at MAX_PARALLEL. Wall clock is set by the deepest
chart rather than the sum, which is the whole point of running them together.

Each chart gets its own log under logs/, so a chart that fails is diagnosable
without unpicking interleaved output. The summary line at the end is what to
read first: any chart with failed or clamped weeks needs triage at source
before its CSV is committed.

    python3 scripts/run_batch_backfill.py plan.json

Concurrency is deliberately modest. These are polite sequential fetches inside
each process, so eight processes is roughly eight requests in flight, not a
flood.
"""
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAX_PARALLEL = 8
ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / 'logs'


def run_one(item):
    slug, spec = item
    csv = ROOT / 'data' / spec['csv']
    log = LOGS / f"{spec['key']}.log"
    started = time.time()
    with log.open('w') as fh:
        proc = subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'backfill_chart.py'),
             slug, str(csv), spec['first_week']],
            stdout=fh, stderr=subprocess.STDOUT, cwd=str(ROOT))
    mins = (time.time() - started) / 60
    tail = log.read_text().strip().splitlines()
    done = next((l for l in reversed(tail) if l.startswith('DONE')), '(no DONE line)')
    print(f'[{spec["key"]}] rc={proc.returncode} {mins:.0f}m {done}', flush=True)
    return {'slug': slug, 'key': spec['key'], 'rc': proc.returncode, 'done': done}


def main():
    plan = json.loads(Path(sys.argv[1]).read_text())
    LOGS.mkdir(exist_ok=True)
    todo = [(s, v) for s, v in plan.items() if v.get('first_week')]
    skipped = [s for s, v in plan.items() if not v.get('first_week')]
    if skipped:
        print(f'SKIPPING {len(skipped)} with no measured first week: {skipped}', flush=True)
    print(f'{len(todo)} charts, {MAX_PARALLEL} at a time', flush=True)

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
        results = list(ex.map(run_one, todo))

    print('\n===== SUMMARY =====', flush=True)
    for r in sorted(results, key=lambda x: x['key']):
        print(f"{r['key']:<32} rc={r['rc']} {r['done']}", flush=True)
    bad = [r['key'] for r in results if r['rc'] != 0]
    print(f'\nnonzero exit: {bad or "none"}', flush=True)


if __name__ == '__main__':
    main()
