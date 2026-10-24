// Monte Carlo projection for the portfolio page: monthly steps, log-normal
// returns with the chosen expected return and volatility, a fixed monthly
// contribution added at the start of each month. Seeded, so the same inputs
// always give the same picture.

interface ProjectionInputs {
  start: number
  monthly: number
  years: number
  expectedReturn: number // a year, e.g. 0.11
  volatility: number // a year, e.g. 0.16
  paths?: number
  seed?: number
}

interface Projection {
  /** per year (0..years): 10th, 50th, 90th percentile values and money put in */
  bands: Array<{ year: number; p10: number; p50: number; p90: number; invested: number }>
  finals: number[] // sorted
}

function rng(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const pick = (sorted: number[], q: number) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.floor(q * (sorted.length - 1))))]

export function project(i: ProjectionInputs): Projection {
  const paths = i.paths ?? 2000
  const months = Math.round(i.years * 12)
  // log-return drift chosen so the average growth is (1 + expectedReturn) a year
  const mu = (Math.log(1 + i.expectedReturn) - (i.volatility * i.volatility) / 2) / 12
  const sd = i.volatility / Math.sqrt(12)
  const rand = rng(i.seed ?? 42)
  const byYear: number[][] = Array.from({ length: i.years + 1 }, () => [])
  const finals: number[] = []
  for (let p = 0; p < paths; p++) {
    let v = i.start
    byYear[0].push(v)
    for (let m = 1; m <= months; m++) {
      const u1 = Math.max(rand(), 1e-12)
      const z = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * rand())
      v = (v + i.monthly) * Math.exp(mu + sd * z)
      if (m % 12 === 0) byYear[m / 12].push(v)
    }
    finals.push(v)
  }
  finals.sort((a, b) => a - b)
  const bands = byYear.map((vals, year) => {
    const s = [...vals].sort((a, b) => a - b)
    return { year, p10: pick(s, 0.1), p50: pick(s, 0.5), p90: pick(s, 0.9), invested: i.start + i.monthly * 12 * year }
  })
  return { bands, finals }
}

/** Share of paths that end at or above the goal. */
export function chance(finals: number[], goal: number): number {
  if (!finals.length) return 0
  let lo = 0
  let hi = finals.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (finals[mid] < goal) lo = mid + 1
    else hi = mid
  }
  return (finals.length - lo) / finals.length
}

/** Monthly contribution that reaches the goal in `confidence` of paths.
 * Each path's final value is linear in the contribution c: A + c * B, with
 * A = start x growth and B = sum of the growth each month's money gets.
 * So the answer is a percentile of each path's own requirement, exact for
 * the same seeded paths as project(). */
export function monthlyNeeded(i: Omit<ProjectionInputs, 'monthly'>, goal: number, confidence = 0.8): number | null {
  const paths = i.paths ?? 2000
  const months = Math.round(i.years * 12)
  const mu = (Math.log(1 + i.expectedReturn) - (i.volatility * i.volatility) / 2) / 12
  const sd = i.volatility / Math.sqrt(12)
  const rand = rng(i.seed ?? 42)
  const need: number[] = []
  for (let p = 0; p < paths; p++) {
    let a = i.start
    let b = 0
    for (let m = 1; m <= months; m++) {
      const u1 = Math.max(rand(), 1e-12)
      const g = Math.exp(mu + sd * Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * rand()))
      a *= g
      b = (b + 1) * g
    }
    need.push(a >= goal ? 0 : b > 0 ? (goal - a) / b : Infinity)
  }
  need.sort((x, y) => x - y)
  const c = need[Math.max(0, Math.ceil(confidence * paths) - 1)]
  return Number.isFinite(c) ? c : null
}
