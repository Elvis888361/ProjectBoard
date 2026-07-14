"""Fractional indexing for task ordering.

Positions are base62 strings that sort lexicographically, so a drag writes one row
instead of renumbering the column. Ported from Greenspan's `fractional-indexing`:
https://observablehq.com/@dgreensp/implementing-fractional-indexing

Key = integer part + optional fraction. The integer part's first char encodes its own
length, which is what keeps append at a constant-length key.
"""

from __future__ import annotations

import math

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
ZERO = "a0"
SMALLEST_INTEGER = "A00000000000000000000000000"


class InvalidPosition(ValueError):
    pass


def _integer_len(head: str) -> int:
    if "a" <= head <= "z":
        return ord(head) - ord("a") + 2
    if "A" <= head <= "Z":
        return ord("Z") - ord(head) + 2
    raise InvalidPosition(f"invalid position head: {head!r}")


def _integer_part(key: str) -> str:
    n = _integer_len(key[0])
    if n > len(key):
        raise InvalidPosition(f"invalid position: {key!r}")
    return key[:n]


def _validate(key: str) -> None:
    if not key:
        raise InvalidPosition("empty position")
    if key == SMALLEST_INTEGER:
        raise InvalidPosition("position is the reserved lower bound")
    integer = _integer_part(key)
    if len(integer) != _integer_len(key[0]):
        raise InvalidPosition(f"invalid position: {key!r}")
    # A trailing zero would give the same value two spellings.
    if key[len(integer) :].endswith(DIGITS[0]):
        raise InvalidPosition(f"position has a trailing zero: {key!r}")


def _increment_integer(x: str) -> str | None:
    head, digits = x[0], list(x[1:])
    carry = True
    for i in range(len(digits) - 1, -1, -1):
        if not carry:
            break
        d = DIGITS.index(digits[i]) + 1
        if d == len(DIGITS):
            digits[i] = DIGITS[0]
        else:
            digits[i] = DIGITS[d]
            carry = False
    if carry:
        if head == "Z":
            return "a" + DIGITS[0]
        if head == "z":
            return None  # out of headroom; caller falls back to a fraction
        h = chr(ord(head) + 1)
        if h > "a":
            digits.append(DIGITS[0])
        else:
            digits.pop()
        return h + "".join(digits)
    return head + "".join(digits)


def _decrement_integer(x: str) -> str | None:
    head, digits = x[0], list(x[1:])
    borrow = True
    for i in range(len(digits) - 1, -1, -1):
        if not borrow:
            break
        d = DIGITS.index(digits[i]) - 1
        if d == -1:
            digits[i] = DIGITS[-1]
        else:
            digits[i] = DIGITS[d]
            borrow = False
    if borrow:
        if head == "a":
            return "Z" + DIGITS[-1]
        if head == "A":
            return None
        h = chr(ord(head) - 1)
        if h < "Z":
            digits.append(DIGITS[-1])
        else:
            digits.pop()
        return h + "".join(digits)
    return head + "".join(digits)


def _midpoint(a: str, b: str | None) -> str:
    """Shortest fraction strictly between `a` and `b`. b=None means 1.0."""
    if b is not None and a >= b:
        raise InvalidPosition(f"{a!r} >= {b!r}")
    if a.endswith(DIGITS[0]) or (b is not None and b.endswith(DIGITS[0])):
        raise InvalidPosition("fraction has a trailing zero")

    if b is not None:
        n = 0
        while n < len(b) and (a[n] if n < len(a) else DIGITS[0]) == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])

    digit_a = DIGITS.index(a[0]) if a else 0
    digit_b = DIGITS.index(b[0]) if b else len(DIGITS)

    if digit_b - digit_a > 1:
        return DIGITS[math.floor(0.5 * (digit_a + digit_b) + 0.5)]

    # Consecutive digits, so we have to go a character deeper.
    if b is not None and len(b) > 1:
        return b[:1]
    return DIGITS[digit_a] + _midpoint(a[1:] if a else "", None)


def key_between(a: str | None, b: str | None) -> str:
    """A position strictly between `a` and `b`.

    a=None prepends, b=None appends, both None is the first task in a column.
    """
    if a is not None:
        _validate(a)
    if b is not None:
        _validate(b)
    if a is not None and b is not None and a >= b:
        raise InvalidPosition(f"positions out of order: {a!r} >= {b!r}")

    if a is None:
        if b is None:
            return ZERO
        ib = _integer_part(b)
        fb = b[len(ib) :]
        if ib == SMALLEST_INTEGER:
            return ib + _midpoint("", fb)
        if ib < b:
            return ib
        dec = _decrement_integer(ib)
        if dec is None:
            raise InvalidPosition("cannot prepend any further")
        return dec

    if b is None:
        ia = _integer_part(a)
        fa = a[len(ia) :]
        inc = _increment_integer(ia)
        return ia + _midpoint(fa, None) if inc is None else inc

    ia = _integer_part(a)
    fa = a[len(ia) :]
    ib = _integer_part(b)
    fb = b[len(ib) :]
    if ia == ib:
        return ia + _midpoint(fa, fb)
    inc = _increment_integer(ia)
    if inc is None:
        raise InvalidPosition("cannot increment any further")
    if inc < b:
        return inc
    return ia + _midpoint(fa, None)
