/**
 * A key that sorts between two positions -- for optimistic rendering only.
 *
 * Deliberately NOT a port of the server's algorithm (backend/app/core/ranking.py). Two
 * implementations of one algorithm in two languages drift, and the drift shows up as a
 * board that's mis-ordered on one client only. This only has to guarantee
 * `before < result < after`, which is enough to draw the card in the right slot for the
 * ~50ms a request is in flight. The server's answer overwrites it.
 */

const MID = 'V' // a digit near the middle of the server's base62 alphabet

export function keyBetween(before: string | null, after: string | null): string {
  if (!before && !after) return 'a0'

  // Appending: any string with `before` as a prefix sorts after it.
  if (before && !after) return before + MID

  // Prepending: a proper prefix of `after` always sorts before it ("ab" < "abc").
  if (!before && after) {
    if (after.length > 1) return after.slice(0, -1)
    return String.fromCharCode(Math.max(48, after.charCodeAt(0) - 1)) // '0' is the floor
  }

  const a = before as string
  const b = after as string

  // Terminates on the first or second try in practice. Falling through to `a` just
  // means we don't reorder optimistically -- cosmetic, not a correctness bug.
  for (let depth = 0; depth < 8; depth++) {
    const candidate = a + MID.repeat(depth + 1)
    if (candidate > a && candidate < b) return candidate
  }
  for (const c of '123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ') {
    const candidate = a + c
    if (candidate > a && candidate < b) return candidate
  }
  return a
}
