"""Tests for the result pagination in the library panel."""

import pytest

from node_runner.library_ui import _paginate


@pytest.mark.parametrize(
    "total,page,size,expected",
    [
        # Fewer results than a page: one page, no slicing.
        (14, 0, 20, (0, 1, 0, 14)),
        (20, 0, 20, (0, 1, 0, 20)),
        # Exactly one over rolls into a second page.
        (21, 0, 20, (0, 2, 0, 20)),
        (21, 1, 20, (1, 2, 20, 21)),
        # Several pages, last one partial.
        (57, 0, 20, (0, 3, 0, 20)),
        (57, 1, 20, (1, 3, 20, 40)),
        (57, 2, 20, (2, 3, 40, 57)),
        # Empty results still report a single page.
        (0, 0, 20, (0, 1, 0, 0)),
        # A page size of one is legal.
        (3, 2, 1, (2, 3, 2, 3)),
    ],
)
def test_paginate(total, page, size, expected):
    assert _paginate(total, page, size) == expected


@pytest.mark.parametrize("page", [3, 9, 1000])
def test_paginate_clamps_past_the_end(page):
    """Filtering down to fewer results must not strand the view on a page
    that no longer exists."""
    current, pages, start, end = _paginate(57, page, 20)
    assert (current, pages) == (2, 3)
    assert (start, end) == (40, 57)


@pytest.mark.parametrize("page", [-1, -50])
def test_paginate_clamps_below_zero(page):
    assert _paginate(57, page, 20)[0] == 0


@pytest.mark.parametrize("size", [0, -5])
def test_paginate_survives_a_nonsense_page_size(size):
    current, pages, start, end = _paginate(10, 0, size)
    assert pages == 10
    assert (current, start, end) == (0, 0, 1)


def test_pages_cover_every_result_exactly_once():
    """Walking the pages must visit all results, in order, with no gaps."""
    rows = list(range(57))
    seen = []
    page, pages = 0, None
    while pages is None or page < pages:
        _current, pages, start, end = _paginate(len(rows), page, 20)
        seen.extend(rows[start:end])
        page += 1
    assert seen == rows
