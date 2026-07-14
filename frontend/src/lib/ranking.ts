/**
 * A key that sorts between two positions -- for optimistic rendering ONLY.
 *
 * The server owns positions. It runs the real fractional-indexing algorithm (see
 * backend/app/core/ranking.py) and its answer is authoritative; `onSuccess` overwrites
 * whatever we guessed here with the row the server actually wrote.
 *
 * So I deliberately did NOT port that algorithm to TypeScript. Two implementations of
 * the same algorithm in two languages is a bug factory: they drift, and the drift shows
 * up as a board that's subtly mis-ordered on one client only. What this function needs
 * to guarantee is exactly one thing, and it's much weaker than what the server needs:
 *
 *     before < result < after     (lexicographically)
 *
 * That's enough to draw the card in the right slot for the ~50ms the request is in
 * flight. It does not need to produce the same string as the server, and it doesn't try
 * to -- it just needs to sort the same way. Keeping the two jobs separate is the point.
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

  // Walk down the alphabet appending to `a` until we land under `b`. In practice this
  // terminates on the first or second try; the loop bound is a guard against a
  // pathological pair, and falling back to `a` (i.e. not reordering optimistically) is
  // a cosmetic no-op, not a correctness bug.
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
