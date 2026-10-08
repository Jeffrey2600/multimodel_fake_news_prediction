import type { Verdict } from './types'

/** Plain-language wording for each verdict. The API keeps its technical names; people see these. */
export const VERDICT: Record<Verdict, { label: string; icon: string; line: string; tone: string }> = {
  Supported: { label: 'Checks out', icon: '✓', line: 'Reliable sources back this up.', tone: 'ok' },
  Contradicted: { label: 'Fake', icon: '✕', line: 'Reliable sources show this isn’t true.', tone: 'bad' },
  Mixed: { label: 'Half true', icon: '◐', line: 'Part of it is right, part is wrong or missing context.', tone: 'mix' },
  Insufficient: { label: 'Can’t confirm', icon: '?', line: 'There isn’t enough reliable information yet to say either way.', tone: 'na' },
}

export function sureness(confidence: number) {
  if (confidence >= 85) return 'We’re very sure'
  if (confidence >= 60) return 'We’re fairly sure'
  return 'We’re not very sure'
}

/** Where the needle sits on the Fake ← Half true → Checks out meter (0–100). */
export function meterPosition(v: Verdict, confidence: number) {
  const c = Math.max(0, Math.min(100, confidence)) / 100
  if (v === 'Contradicted') return 30 - 24 * c
  if (v === 'Supported') return 70 + 24 * c
  return 50
}
