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


def test_panel_max_width_subtracts_both_rails():
    """The panel's budget must account for the rail on BOTH sides.

    Left rail, because it pushes the panel's left edge inward; right rail,
    because the panel must stop before it.
    """
    panel = _rule(NAV, '.nav-dd-panel')
    max_width = _decl(panel, 'max-width')
    assert 'var(--page-inset' in max_width, (
        'panel max-width does not reference --page-inset, so it is budgeting '
        f'from the raw viewport edge again: {max_width!r}'
    )
    assert re.search(r'2\s*\*\s*var\(--page-inset', max_width), (
        f'panel max-width must subtract the inset twice, once per rail: {max_width!r}'
    )


def _eval_cap(expr, viewport, inset):
    """Evaluate a CSS calc() for max-width in px.

    Resolves the units this rule actually uses so the test measures the shipped
    formula rather than a copy of it — dropping a term or halving a factor has
    to fail here.
    """
    m = re.fullmatch(r'calc\((.*)\)', expr.strip(), re.S)
    assert m, f'panel max-width is not a calc(): {expr!r}'
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


@pytest.mark.parametrize('viewport', [1100, 1280, 1440, 1512, 1920, 2560])
def test_open_panel_right_edge_stays_inside_the_viewport(viewport):
    """The arithmetic the three earlier fixes never did.

    The panel always reaches its cap on a real window: six groups of chart
    names measure ~1600px, wider than any cap here. So the cap IS the panel's
    width, and the cap plus where the panel starts has to land on screen.
    """
    inset = _page_inset_px()
    left_edge = inset + NAV_PADDING_PX
    cap = _eval_cap(_decl(_rule(NAV, '.nav-dd-panel'), 'max-width'), viewport, inset)
    right_edge = left_edge + cap
    assert right_edge <= viewport, (
        f'at {viewport}px the panel reaches {right_edge}px, overflowing by '
        f'{right_edge - viewport}px — the page scrolls sideways'
    )

