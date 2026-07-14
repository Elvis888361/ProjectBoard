const MID = 'V' 
export function keyBetween(before: string | null, after: string | null): string {
  if (!before && !after) return 'a0'

  if (before && !after) return before + MID

  if (!before && after) {
    if (after.length > 1) return after.slice(0, -1)
    return String.fromCharCode(Math.max(48, after.charCodeAt(0) - 1))
  }

  const a = before as string
  const b = after as string

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
