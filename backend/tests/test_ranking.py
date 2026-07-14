"""Unit tests for fractional indexing.

This is the backend business logic I most wanted covered. It's the only place in the
app with a real algorithm -- everything else is SQL and HTTP plumbing, where an
integration test gives better value per line. And its failure mode is nasty: a subtly
wrong key generator doesn't crash, it just quietly corrupts the order of everybody's
board, and you find out from a user.

The invariant under test is the only one that matters: after any sequence of moves,
sorting by the generated keys reproduces the order the user asked for.
"""

import random

import pytest

from app.core.ranking import InvalidPosition, key_between


def test_first_key_in_an_empty_column():
    assert key_between(None, None) == "a0"


def test_append_keeps_keys_ordered():
    keys = []
    prev = None
    for _ in range(50):
        prev = key_between(prev, None)
        keys.append(prev)
    assert keys == sorted(keys)


def test_append_does_not_grow_the_key():
    """The whole reason for the integer/fraction split.

    A naive midpoint-of-(0,1) scheme grows the key by a character on every append, and
    appending is the most common operation on a board. Here 1000 appends stay short.
    """
    prev = None
    for _ in range(1000):
        prev = key_between(prev, None)
    assert len(prev) <= 5, f"append-only keys grew to {len(prev)} chars: {prev!r}"


def test_prepend_keeps_keys_ordered():
    keys = []
    first = None
    for _ in range(50):
        first = key_between(None, first)
        keys.insert(0, first)
    assert keys == sorted(keys)


def test_insert_between_two_keys():
    a = key_between(None, None)
    b = key_between(a, None)
    mid = key_between(a, b)
    assert a < mid < b


def test_repeated_insert_into_the_same_gap_stays_ordered():
    """The pathological case: always insert at the same spot.

    This is what makes keys grow, and it's the thing I'd watch in production. 200 of
    them is far past anything a human does by dragging. The keys get long; they must
    not get *wrong*.
    """
    lo = key_between(None, None)
    hi = key_between(lo, None)
    for _ in range(200):
        mid = key_between(lo, hi)
        assert lo < mid < hi
        hi = mid  # squeeze into the same gap again


def test_random_moves_preserve_order():
    """Fuzz. Model the column as a list, do random inserts, assert the DB's ORDER BY
    (which is `ORDER BY position`) would reproduce the list."""
    rng = random.Random(1234)  # seeded: a failure here must be reproducible
    column: list[str] = []

    for _ in range(300):
        i = rng.randint(0, len(column))
        before = column[i - 1] if i > 0 else None
        after = column[i] if i < len(column) else None
        column.insert(i, key_between(before, after))

    assert column == sorted(column), "sorting by position no longer reproduces board order"
    assert len(set(column)) == len(column), "two tasks were given the same position"


def test_rejects_reversed_bounds():
    a = key_between(None, None)
    b = key_between(a, None)
    with pytest.raises(InvalidPosition):
        key_between(b, a)


def test_rejects_a_malformed_position():
    # Guards the API boundary: a client (or a bad migration) handing us junk should
    # fail loudly here rather than write an unsortable key into the tasks table.
    with pytest.raises(InvalidPosition):
        key_between("!!not-a-key", None)
