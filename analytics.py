"""Visitor counting for the private /admin page.

Deliberately imports no Flask, so it can be tested on its own. app.py's only
contact with this module is init_db() at startup, record_visit() from a
before_request hook, and summary() from the admin route.

Nothing here may ever raise into a request. Counting is the least important
thing this site does; serving charts is the most. Every public function
swallows its own failures and reports them through its return value.
"""
import hashlib
import hmac
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Railway wipes the container filesystem on every deploy, so the default lives
# on the mounted volume rather than beside the code. A local path here would
# lose every number at the next `railway up`.
DEFAULT_DB = '/data/analytics.db'

# Set when the database cannot be opened — most likely the volume is not
# attached. The module then no-ops rather than throwing once per request.
_disabled = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    day   TEXT NOT NULL,
    path  TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, path)
);
CREATE TABLE IF NOT EXISTS visitors (
    visitor_hash TEXT PRIMARY KEY,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    visits       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS visitor_days (
    visitor_hash TEXT NOT NULL,
    day          TEXT NOT NULL,
    PRIMARY KEY (visitor_hash, day)
);
"""


def db_path():
    """Read the env var per call so tests can repoint it without reimporting."""
    return os.environ.get('ANALYTICS_DB', DEFAULT_DB)


def _today():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _connect():
    conn = sqlite3.connect(db_path(), timeout=5)
    # gunicorn runs several workers against this one file. WAL lets readers and
    # a writer coexist; the busy timeout absorbs the brief lock contention that
    # remains instead of surfacing 'database is locked' to a visitor.
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    return conn


def visitor_hash(ip, user_agent):
    """Salted hash of IP + user-agent. The raw IP is never stored.

    ANALYTICS_SALT must be a FIXED env var. A per-boot random salt would make
    every returning visitor look new and reset the lifetime count on each
    deploy, which is a silent, unrecoverable corruption of the only number this
    page exists to report — hence a stable fallback and a warning, never
    os.urandom().
    """
    salt = os.environ.get('ANALYTICS_SALT')
    if not salt:
        log.warning('ANALYTICS_SALT is unset; using the stable fallback. Set it '
                    'in Railway. Changing it later resets unique counts.')
        salt = 'billboard-chart-archive-default-salt'
    raw = f'{salt}:{ip or ""}:{user_agent or ""}'.encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:16]


def init_db():
    """Create the tables. Returns False and disables counting if that fails."""
    global _disabled
    try:
        path = db_path()
        parent = os.path.dirname(path)
        if parent and 'ANALYTICS_DB' in os.environ:
            # An explicit path is a test or a local run: create it freely.
            os.makedirs(parent, exist_ok=True)
        elif parent and not os.path.isdir(parent):
            # The DEFAULT path must NOT be created. makedirs would happily make
            # /data on the container's own disk, counting would report itself
            # healthy, and Railway would wipe every number on the next deploy —
            # a silent reset, which is worse than not counting. Railway creates
            # this directory only when a volume is mounted there, so its absence
            # is the signal, and the admin page says so rather than showing a
            # zero that looks like real data.
            raise RuntimeError(f'{parent} is not a mounted volume')
        with _connect() as conn:
            conn.executescript(SCHEMA)
        _disabled = False
        return True
    except Exception as exc:
        # Almost always the Railway volume not being attached at /data. The
        # site must still serve charts, so counting turns itself off.
        log.warning('analytics disabled, could not open %s: %s', db_path(), exc)
        _disabled = True
        return False


def record_visit(path, ip, user_agent, day=None):
    """Count one pageview. Never raises. Returns True when it was recorded."""
    if _disabled:
        return False
    day = day or _today()
    try:
        vhash = visitor_hash(ip, user_agent)
        with _connect() as conn:
            conn.execute(
                'INSERT INTO visits (day, path, views) VALUES (?, ?, 1) '
                'ON CONFLICT(day, path) DO UPDATE SET views = views + 1',
                (day, path))
            # first_seen is written once and never touched again — that is what
            # makes visitors.rowcount a true lifetime figure.
            conn.execute(
                'INSERT INTO visitors (visitor_hash, first_seen, last_seen, visits) '
                'VALUES (?, ?, ?, 1) '
                'ON CONFLICT(visitor_hash) DO UPDATE SET '
                'last_seen = excluded.last_seen, visits = visits + 1',
                (vhash, day, day))
            conn.execute(
                'INSERT OR IGNORE INTO visitor_days (visitor_hash, day) VALUES (?, ?)',
                (vhash, day))
        return True
    except Exception as exc:
        log.warning('analytics: failed to record %s: %s', path, exc)
        return False


def summary(days=30, top=10):
    """Everything the admin page shows. Never raises; returns zeros on failure."""
    empty = dict(lifetime_uniques=0, total_views=0, today_uniques=0,
                 today_views=0, recent=[], top_paths=[], available=False)
    if _disabled:
        return empty
    today = _today()
    try:
        with _connect() as conn:
            lifetime = conn.execute('SELECT COUNT(*) FROM visitors').fetchone()[0]
            total = conn.execute('SELECT COALESCE(SUM(views), 0) FROM visits').fetchone()[0]
            today_u = conn.execute(
                'SELECT COUNT(*) FROM visitor_days WHERE day = ?', (today,)).fetchone()[0]
            today_v = conn.execute(
                'SELECT COALESCE(SUM(views), 0) FROM visits WHERE day = ?',
                (today,)).fetchone()[0]

            since = (datetime.now(timezone.utc) - timedelta(days=days - 1)).strftime('%Y-%m-%d')
            # Views and uniques are counted in separate tables, so they are
            # joined by day here rather than in SQL — a LEFT JOIN across both
            # would multiply the view sums by the visitor count.
            views_by_day = dict(conn.execute(
                'SELECT day, SUM(views) FROM visits WHERE day >= ? GROUP BY day',
                (since,)).fetchall())
            uniq_by_day = dict(conn.execute(
                'SELECT day, COUNT(*) FROM visitor_days WHERE day >= ? GROUP BY day',
                (since,)).fetchall())
            recent = [
                dict(day=d, views=views_by_day.get(d, 0), uniques=uniq_by_day.get(d, 0))
                for d in sorted(set(views_by_day) | set(uniq_by_day), reverse=True)
            ]

            top_paths = [
                dict(path=p, views=v) for p, v in conn.execute(
                    'SELECT path, SUM(views) AS v FROM visits '
                    'GROUP BY path ORDER BY v DESC LIMIT ?', (top,)).fetchall()
            ]
        return dict(lifetime_uniques=lifetime, total_views=total,
                    today_uniques=today_u, today_views=today_v,
                    recent=recent, top_paths=top_paths, available=True)
    except Exception as exc:
        log.warning('analytics: summary failed: %s', exc)
        return empty


def check_password(supplied):
    """Constant-time check against ADMIN_PASSWORD. False when it is unset."""
    expected = os.environ.get('ADMIN_PASSWORD')
    if not expected:
        log.warning('ADMIN_PASSWORD is unset; /admin refuses every login.')
        return False
    return hmac.compare_digest(str(supplied or ''), expected)
