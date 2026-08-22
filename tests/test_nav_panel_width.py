"""The chart menu must fit inside the viewport it is drawn in.

The panel is `position: absolute` and nothing on the way up to <body> clips it,
so a panel wider than the space to its right does not scroll itself — it grows
the document's scrollable area and the whole PAGE scrolls sideways. Three
separate fixes to the panel's own width missed this because they all tuned how
wide the panel wants to be, never what it is measured against.

What it is measured against is the bug: paxel.css insets <body> by a rail width
on each side at >=1100px, so the panel's left edge is that rail plus the nav's
padding away from the viewport edge, while its `max-width` budgeted from the nav
padding alone. Two numbers in two files that have to agree.

These tests read both files and check they still do, so the pair cannot drift
apart again silently.

The nav's own panel now answers that by shifting OUT over the left rail rather
than by shrinking away from it — the rails are decorative and it paints over
them anyway — which is the same two-numbers-in-two-files problem pointed the
other way, plus a new edge to check: an overshoot puts the panel off the left of
the viewport, where the page cannot scroll to reach it.
"""
import functools
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAXEL = (ROOT / 'static' / 'paxel.css').read_text()
NAV = (ROOT / 'templates' / '_nav.html').read_text()

# .nav's own horizontal padding, in px. The panel sits at the nav's padding
# edge, so this is on top of the body inset.
NAV_PADDING_PX = 24


def _rule(css, selector):
    """The declaration block for `selector`, comments stripped."""
    stripped = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    m = re.search(re.escape(selector) + r'\s*\{(.*?)\}', stripped, re.S)
    assert m, f'no rule found for {selector!r}'
    return m.group(1)


def _decl(block, prop):
    m = re.search(rf'(?<![\w-]){re.escape(prop)}\s*:\s*([^;]+);', block)
    assert m, f'no {prop!r} declaration in {block!r}'
    return m.group(1).strip()


def _page_inset_px():
    """--page-inset at the widest breakpoint, as an int of px."""
    m = re.search(r'--page-inset\s*:\s*(\d+)px', PAXEL.split('@media (min-width: 1100px)')[1])
    assert m, '--page-inset is not set inside the >=1100px rail block'
    return int(m.group(1))


def test_body_rails_are_driven_by_the_page_inset_variable():
    """The rail width must be the variable, not a literal.

    A literal here is the whole bug: it is invisible to the nav, which then
    budgets against a viewport edge that the rails already moved.
    """
    rails = PAXEL.split('@media (min-width: 1100px)')[1]
    body = _rule(rails, 'body')
    assert 'var(--page-inset' in _decl(body, 'padding-left')
    assert 'var(--page-inset' in _decl(body, 'padding-right')


def test_page_inset_defaults_to_zero_below_the_rail_breakpoint():
    """Below 1100px there are no rails, so the panel gets the full viewport."""
    base = PAXEL.split('@media')[0]
    assert re.search(r'--page-inset\s*:\s*0px', base), (
        '--page-inset has no 0px default; below the breakpoint the nav calc '
        'would fall back to its own default and silently stop matching <body>'
    )


def _base_panel():
    """The shared .nav-dd-panel rule — the nav's copy AND dropouts.html's."""
    return _rule(NAV, '.nav-dd-panel')


def _nav_panel():
    """The nav-scoped override, which reclaims the left rail for the menu."""
    return _rule(NAV, '.nav .nav-dd-panel')


def _effective(prop):
    """`prop` as it resolves on the NAV's panel at >=1100px.

    Two rules apply to it: the shared one and the nav-scoped override. The
    override is more specific, so it wins wherever it declares something.
    """
    override = _nav_panel()
    if re.search(rf'(?<![\w-]){re.escape(prop)}\s*:', override):
        return _decl(override, prop)
    return _decl(_base_panel(), prop)


def test_panel_start_accounts_for_the_left_rail():
    """The left rail moves the panel's start, so the geometry must know it.

    Either the panel subtracts the rail from its cap or it shifts out past the
    rail and takes the width back — both are valid, and which one is shipped is
    checked arithmetically below. What is never valid is neither: a panel that
    budgets from the raw viewport edge while starting a rail's width in is the
    original sideways-scroll bug.
    """
    geometry = _effective('left') + ' ' + _effective('max-width')
    assert 'var(--page-inset' in geometry, (
        'neither the panel\'s left nor its max-width references --page-inset, '
        f'so it is budgeting from the raw viewport edge again: {geometry!r}'
    )


def test_the_shared_panel_rule_is_not_pulled_out_past_the_rail():
    """The rail reclaim must stay scoped to the nav.

    dropouts.html reuses .nav-dd-panel for its chart picker, and that copy is
    drawn mid-page after a <label> inside a centred .wrap — not at the body's
    padding edge. A negative offset on the shared rule would drag it a rail's
    width away from the summary it belongs to.
    """
    left = _decl(_base_panel(), 'left')
    assert '-' not in left, (
        'the shared .nav-dd-panel rule offsets the panel leftwards; that also '
        f"moves dropouts.html's picker, which does not start at the rail: {left!r}"
    )


def _split_args(text):
    """Top-level comma split, so nested calc()s inside a clamp() stay whole."""
    depth, out, cur = 0, [], ''
    for ch in text:
        if ch == ',' and depth == 0:
            out.append(cur)
            cur = ''
            continue
        depth += (ch == '(') - (ch == ')')
        cur += ch
    return out + [cur]


def _eval_len(expr, viewport, inset=0):
    """Evaluate a CSS length — bare, calc(), or clamp()/min()/max() — in px.

    Resolves the units these rules actually use so the test measures the
    shipped formula rather than a copy of it — dropping a term or halving a
    factor has to fail here.
    """
    body = expr.strip()
    m = re.fullmatch(r'(clamp|min|max)\((.*)\)', body, re.S)
    if m:
        vals = [_eval_len(a, viewport, inset) for a in _split_args(m.group(2))]
        # clamp(low, val, high) is the median of its three arguments.
        return {'clamp': lambda v: sorted(v)[1], 'min': min, 'max': max}[m.group(1)](vals)
    m = re.fullmatch(r'calc\((.*)\)', body, re.S)
    if m:
        body = m.group(1)
    body = re.sub(r'var\(--page-inset[^)]*\)', str(inset), body)
    body = re.sub(r'(\d*\.?\d+)rem', lambda x: str(float(x.group(1)) * 16), body)
    body = re.sub(r'(\d*\.?\d+)vw', lambda x: str(float(x.group(1)) / 100 * viewport), body)
    body = re.sub(r'(\d*\.?\d+)px', lambda x: x.group(1), body)
    # Arithmetic only: the whitelist below leaves nothing but digits and
    # operators, and the eval runs with no builtins and no names in scope, so
    # there is no identifier left for it to resolve to anything.
    assert re.fullmatch(r'[\d\s.+\-*/()]+', body), f'unresolved units in {body!r}'
    return eval(body, {'__builtins__': {}}, {})


def _panel_edges(viewport):
    """Where the open menu's left and right edges land, in px from the left.

    The panel is abspos in a .nav-dd that is the nav's first child, so its
    static position is the body inset plus the nav's padding. `left` then moves
    it from there — negative, out over the rail, once it reclaims that width.
    """
    inset = _page_inset_px()
    left_edge = inset + NAV_PADDING_PX + _eval_len(_effective('left'), viewport, inset)
    return left_edge, left_edge + _eval_len(_effective('max-width'), viewport, inset)


@pytest.mark.parametrize('viewport', [1100, 1280, 1440, 1512, 1920, 2560])
def test_open_panel_right_edge_stays_inside_the_viewport(viewport):
    """The arithmetic the three earlier fixes never did.

    The cap bounds the panel whether or not the content reaches it — since the
    one-line rules below size the type to fit, the row now sits inside the cap
    rather than against it — so the cap plus where the panel starts is still
    what has to land on screen.
    """
    _, right_edge = _panel_edges(viewport)
    assert right_edge <= viewport, (
        f'at {viewport}px the panel reaches {right_edge}px, overflowing by '
        f'{right_edge - viewport}px — the page scrolls sideways'
    )


@pytest.mark.parametrize('viewport', [1100, 1280, 1440, 1512, 1920, 2560])
def test_open_panel_left_edge_stays_inside_the_viewport(viewport):
    """The failure mode the rail reclaim introduces, in the other direction.

    Pulling the panel out over the left rail is a negative offset, and one
    that overshoots puts content off the left edge — where, unlike the right,
    the page cannot even be scrolled to reach it.
    """
    left_edge, _ = _panel_edges(viewport)
    assert left_edge >= 0, (
        f'at {viewport}px the panel starts at {left_edge}px, off the left edge '
        'of the viewport — that width is unreachable, not merely clipped'
    )


def test_panel_has_no_min_width_floor():
    """A min-width floor outranks max-width and re-creates the overflow.

    This has now happened twice (a 180px floor on .nav-dd-group, a 460px floor
    here). Both times the panel could no longer shrink to its cap and pushed
    the page sideways instead.
    """
    for panel in (_base_panel(), _nav_panel()):
        assert not re.search(r'(?<![\w-])min-width\s*:\s*[1-9]', panel), (
            'a min-width floor is back on .nav-dd-panel; min-width beats '
            'max-width, so the panel can no longer shrink to fit the viewport'
        )


# ---------------------------------------------------------------------------
# No chart name breaks over two lines.
#
# The rules above keep the panel inside the viewport. These keep the CONTENT
# inside the panel, which is the other half of the same budget: the row of
# columns is as wide as the sum of each column's longest chart name, and that
# is decided by the registry, not by the CSS. The names used to absorb any
# shortfall by wrapping. They no longer may, so the shortfall has to be proved
# gone at every width the grid is used at — and re-proved whenever a chart is
# added, which is what these measure.
# ---------------------------------------------------------------------------

APP = ROOT / 'app.py'
# The weights the panel actually renders at: links are 500, headings 600.
# Vendored so this can measure real text rather than guess at an average glyph
# width; the page still loads the same faces from Google Fonts.
FONT_LINK = ROOT / 'static' / 'fonts' / 'SpaceGrotesk-Medium.ttf'
FONT_LABEL = ROOT / 'static' / 'fonts' / 'SpaceGrotesk-SemiBold.ttf'


@functools.lru_cache(maxsize=None)
def _font(path):
    from fontTools.ttLib import TTFont

    font = TTFont(path)
    return font['head'].unitsPerEm, font.getBestCmap(), font['hmtx']


@functools.lru_cache(maxsize=None)
def _advance(font_path, text):
    """Width of `text` per px of font size — cached, since the fit is measured
    at a dozen viewports and only the size changes between them."""
    upem, cmap, hmtx = _font(font_path)
    fallback = cmap[ord('n')]
    return sum(hmtx[cmap.get(ord(c), fallback)][0] for c in text) / upem


def _text_width(font_path, text, size):
    """Advance width of `text` at `size` px, in px.

    Sums glyph advances and ignores kerning, which browsers apply and which
    almost always pulls text in — so this reads slightly WIDE, in the direction
    that makes a pass here mean a pass in a browser. The margin below covers
    the rest of that gap.
    """
    return _advance(font_path, text) * size


def _assignment(tree, name):
    import ast

    return next(
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(getattr(t, 'id', None) == name for t in n.targets)
    )


def _registry_groups():
    """{group: [label]} for every chart the nav can list.

    Read with ast rather than by importing app, which loads every chart's CSV —
    a ninety-second import for a fact that is sitting in the source. app.py
    registers charts from three places and this has to mirror all three, or a
    group the template renders comes back empty and the fit is measured against
    less than the panel actually draws:
      - the CHARTS literal, written as dict(label=..., group=...) calls;
      - BATCH_CHARTS, whose tuples app.py folds into CHARTS;
      - and the Hits of the World entries BATCH_CHARTS is extended with from
        HOTW_COUNTRIES, one per country, labelled '<country> Songs'.
    """
    import ast

    tree = ast.parse(APP.read_text())
    groups = {}

    def add(group, label):
        groups.setdefault(group, []).append(label)

    for entry in _assignment(tree, 'CHARTS').values:
        kw = {k.arg: k.value for k in entry.keywords}
        add(kw['group'].value, kw['label'].value)
    for label, group, *_ in ast.literal_eval(_assignment(tree, 'BATCH_CHARTS')).values():
        add(group, label)
    for _stem, country in ast.literal_eval(_assignment(tree, 'HOTW_COUNTRIES')):
        add('Hits of the World', f'{country} Songs')
    return groups


@functools.lru_cache(maxsize=None)
def _columns():
    """[(heading, tuple of label)] in the order the panel lays them out.

    The order comes from app.py's CHART_GROUP_ORDER, which is what the nav
    iterates, so a group added there is measured without touching this file.
    It used to be read from literal nav_group() calls in the template; those
    became a loop when the dropouts picker was made to share the same list.
    """
    import ast

    groups = _registry_groups()
    order = ast.literal_eval(_assignment(ast.parse(APP.read_text()), 'CHART_GROUP_ORDER'))
    assert order, 'CHART_GROUP_ORDER is empty — the panel would measure as no columns'
    cols = [(g, groups[g]) for g in order]
    # The Year-End column holds whichever charts have a year-end edition, which
    # depends on loaded data. Measuring it against every label in the registry
    # is the conservative reading and keeps the CSVs out of this test.
    cols.append(('Year-End', [l for labels in groups.values() for l in labels]))
    # The template shortens this one heading; the full name is wider than both
    # links under it. Tuples so this stays hashable for the cache above.
    return tuple((('Albums' if g == 'Albums & Artists' else g), tuple(labels))
                 for g, labels in cols)


def _padding_x(block):
    """Horizontal padding from a `padding` shorthand, in px."""
    parts = _decl(block, 'padding').split()
    return _eval_len(parts[1] if len(parts) > 1 else parts[0], 0)


def _stack_breakpoint():
    """First width at which the grid still lays the groups out in columns.

    Below it the flow stacks, and a stacked group is as wide as the panel, so
    nothing shrinks and nothing spills — that is the only sanctioned way to run
    out of width now that the names cannot wrap.
    """
    m = re.search(
        r'@media \(max-width: (\d+)px\)\s*\{\s*\.nav \.nav-dd-flow\s*\{[^}]*grid-auto-flow:\s*row',
        re.sub(r'/\*.*?\*/', '', NAV, flags=re.S), re.S,
    )
    assert m, 'no max-width media query stacks .nav .nav-dd-flow into rows'
    return int(m.group(1)) + 1


def _row_width(viewport):
    """Width the 7 columns need at `viewport`, in px, from the shipped CSS."""
    link_size = _eval_len(_decl(_rule(NAV, '.nav .nav-dd-panel a'), 'font-size'), viewport)
    link_pad = _padding_x(_rule(NAV, '.nav-dd-group a'))

    heading = _rule(NAV, '.nav-dd-label')
    head_size = _eval_len(_decl(heading, 'font-size'), viewport)
    head_pad = _padding_x(heading)
    # letter-spacing is in em and CSS adds it after every character, the last
    # one included.
    tracking = float(re.fullmatch(r'([\d.]+)em', _decl(heading, 'letter-spacing')).group(1))

    flow = _rule(NAV, '.nav-dd-flow')
    gap = _eval_len(_decl(flow, 'gap'), viewport)
    panel = _base_panel()
    padding = _padding_x(panel)
    border = _eval_len(_decl(panel, 'border').split()[0], viewport)

    columns = _columns()
    total = 0
    for head, labels in columns:
        links = max(_text_width(FONT_LINK, l, link_size) for l in labels) + 2 * link_pad
        # Headings are uppercased by text-transform and do NOT scale with the
        # links' fluid size, so at the small end they can be the wider of the
        # two — 'HITS OF THE WORLD' nearly is.
        label = (_text_width(FONT_LABEL, head.upper(), head_size)
                 + tracking * head_size * len(head) + 2 * head_pad)
        total += max(links, label)
    return total + (len(columns) - 1) * gap + 2 * padding + 2 * border


# How much of the cap is held back as margin. The test measures glyph advances;
# a browser also applies kerning and hinting and lands within about a percent of
# this, so a fit measured to the last pixel here is not a fit on screen.
SAFETY = 0.015

FIT_WIDTHS = [_stack_breakpoint(), 1280, 1366, 1400, 1440, 1512, 1728, 1920, 2560]


def _cap(viewport):
    return _eval_len(_effective('max-width'), viewport, _page_inset_px())


@functools.lru_cache(maxsize=None)
def _narrowest_fitting_width():
    """Narrowest viewport whose panel still holds the columns, with margin."""
    return next(v for v in range(900, 1700)
                if _row_width(v) <= _cap(v) * (1 - SAFETY))


def test_the_links_may_not_wrap():
    """The promise itself. Everything else here exists to make it safe."""
    ws = _decl(_rule(NAV, '.nav-dd-group a'), 'white-space')
    assert ws == 'nowrap', (
        f'chart names are set to white-space: {ws} — a name long enough to '
        'wrap reads as two charts in a list of one-line entries'
    )


@pytest.mark.parametrize('viewport', FIT_WIDTHS)
def test_every_chart_name_fits_on_one_line(viewport):
    """The row of columns has to fit the panel, at every width it is drawn at.

    A name that no longer fits cannot wrap now — the track shrinks and its text
    spills over the next column — so this failing means one of: a new chart with
    a long name, a type size or padding raised, or the stack breakpoint lowered
    past what the 11px floor can carry. Shorten the name, or take the width back
    somewhere else; do not restore wrapping.
    """
    row, cap = _row_width(viewport), _cap(viewport)
    assert row <= cap * (1 - SAFETY), (
        f'at {viewport}px the chart names need {row:.0f}px against a '
        f'{cap:.0f}px cap, leaving {cap - row:.0f}px of the {cap * SAFETY:.0f}px '
        'margin this needs — the longest names break over two lines'
    )


def test_the_grid_stacks_exactly_where_the_columns_stop_fitting():
    """The breakpoint is a measurement, not a taste call, in both directions.

    Set it too low and the widths between it and the real limit draw columns
    that cannot hold their names — the promise breaks there, silently, because
    nowrap fails by spilling rather than by wrapping. Set it too high and
    perfectly good column layouts are thrown away for a stacked list.
    """
    breakpoint_, limit = _stack_breakpoint(), _narrowest_fitting_width()
    assert breakpoint_ >= limit, (
        f'the grid keeps its columns down to {breakpoint_}px but they only fit '
        f'to {limit}px; between the two, chart names spill into the next column'
    )
    assert breakpoint_ <= limit + 30, (
        f'the grid stacks at {breakpoint_}px though the columns still fit at '
        f'{limit}px — {breakpoint_ - limit}px of usable layout given up'
    )
