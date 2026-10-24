// Same two-stage DCF as src/services/dcf.py, so the page can recompute as the
// viewer edits the assumptions. Keep the two in step.

interface DcfInputs {
  fcf: number
  growth: number
  discount: number
  terminal: number
  netCash: number
  shares: number
  highYears: number
  totalYears: number
}

/** Per-share model value; null when discount <= terminal (no finite answer). */
export function modelValue(i: DcfInputs): number | null {
  if (i.discount <= i.terminal || i.shares <= 0) return null
  let pv = 0
  let cash = i.fcf
  for (let year = 1; year <= i.totalYears; year++) {
    const g =
      year <= i.highYears ? i.growth : i.growth + ((i.terminal - i.growth) * (year - i.highYears)) / (i.totalYears - i.highYears)
    cash *= 1 + g
    pv += cash / (1 + i.discount) ** year
  }
  const tv = (cash * (1 + i.terminal)) / (i.discount - i.terminal)
  pv += tv / (1 + i.discount) ** i.totalYears
  return (pv + i.netCash) / i.shares
}

/** Years 1-5 growth the price implies, null outside -50%..+100%. */
export function impliedGrowth(price: number, i: Omit<DcfInputs, 'growth'>): number | null {
  const gap = (g: number) => {
    const v = modelValue({ ...i, growth: g })
    return v == null ? null : v - price
  }
  let lo = -0.5
  let hi = 1
  const a = gap(lo)
  const b = gap(hi)
  if (a == null || b == null || a > 0 || b < 0) return null
  for (let k = 0; k < 80; k++) {
    const mid = (lo + hi) / 2
    if ((gap(mid) ?? 0) < 0) lo = mid
    else hi = mid
  }
  return (lo + hi) / 2
}
