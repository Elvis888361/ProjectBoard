"""Tests fractional indexing algorithm ensuring correct, stable task ordering behavior."""

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
    """Ensures repeated appends keep generated position keys compact."""
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
    """Verifies repeated inserts maintain correct ordering within identical gaps."""
    lo = key_between(None, None)
    hi = key_between(lo, None)
    for _ in range(200):
        mid = key_between(lo, hi)
        assert lo < mid < hi
        hi = mid


def test_random_moves_preserve_order():
    """Fuzz: random inserts, then assert ORDER BY position reproduces the list."""
    rng = random.Random(1234)
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
    with pytest.raises(InvalidPosition):
        key_between("!!not-a-key", None)
