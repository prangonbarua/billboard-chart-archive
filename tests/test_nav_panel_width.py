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


def _eval_len(expr, viewport, inset):
    """Evaluate a CSS length — a bare value or a calc() — in px.

    Resolves the units these rules actually use so the test measures the
    shipped formula rather than a copy of it — dropping a term or halving a
    factor has to fail here.
    """
    body = expr.strip()
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

    The panel always reaches its cap on a real window: seven groups of chart
    names measure ~1600px, wider than any cap here. So the cap IS the panel's
    width, and the cap plus where the panel starts has to land on screen.
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
