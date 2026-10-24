import { useEffect, useState } from 'react'
import { cx } from '../lib/cx'

// Loading state for the Market insights panels: a small candlestick chart
// that draws itself, a scan line, what the panel is working on right now and
// a rotating market tip, so a few seconds of waiting reads as progress rather
// than a frozen grey block. The chart is decoration (fixed shapes, not data).

const TIPS = [
  "A candle's body runs from open to close; the thin wicks mark the day's high and low.",
  'Breadth counts how many stocks rose versus fell. It can disagree with the index when a few giants carry it.',
  'On a rotation chart, right means stronger than the index and up means that strength is rising.',
  "NSE's normal trading session runs from 9:15 am to 3:30 pm IST, Monday to Friday.",
  "A bulk deal is a single client trading more than 0.5% of a company's shares in one day.",
  'Beta measures how much a stock tends to move for a 1% move in something else, like the market or crude.',
  "The RBI repo rate is what the central bank charges banks for overnight money; it anchors loan rates.",
  'A 52-week high or low is the highest or lowest price of the last year, a common reference for traders.',
]

// Candles as [open, close] in a 240 x 80 box (y grows down, so a smaller
// close than open is an up candle); wicks extend a little past the body.
const OC: [number, number][] = [
  [62, 54], [54, 60], [60, 46], [46, 50], [50, 38], [38, 44],
  [44, 30], [30, 36], [36, 24], [24, 28], [28, 16], [16, 12],
]
const CANDLES = OC.map(([o, c], i) => {
  const x = 16 + i * 19
  return { x, o, c, h: Math.min(o, c) - 4 - (i % 3), l: Math.max(o, c) + 3 + (i % 2) * 2 }
})
const TREND = 'M' + CANDLES.map((k) => `${k.x} ${(k.o + k.c) / 2}`).join(' L')

export default function InsightLoader({
  steps,
  className,
}: {
  /** What the panel is doing, in order; the last one stays until data lands. */
  steps: string[]
  className?: string
}) {
  const [step, setStep] = useState(0)
  const [tip, setTip] = useState(() => Math.floor(Math.random() * TIPS.length))

  useEffect(() => {
    const s = window.setInterval(() => setStep((i) => Math.min(i + 1, steps.length - 1)), 1400)
    const t = window.setInterval(() => setTip((i) => (i + 1) % TIPS.length), 4500)
    return () => {
      window.clearInterval(s)
      window.clearInterval(t)
    }
  }, [steps.length])

  return (
    <div
      role="status"
      aria-live="polite"
      className={cx(
        'insight-loader relative flex flex-col items-center justify-center gap-4 overflow-hidden rounded-lg bg-canvas px-4 py-6 text-center',
        className,
      )}
    >
      <svg viewBox="0 0 240 80" className="h-28 w-full max-w-[380px]" aria-hidden="true">
        {[20, 40, 60].map((y) => (
          <line key={y} x1="0" x2="240" y1={y} y2={y} className="stroke-line" strokeOpacity="0.5" strokeDasharray="2 4" />
        ))}
        {CANDLES.map(({ x, o, c, h, l }, i) => {
          const up = c < o
          return (
            <g
              key={x}
              className={cx('insight-loader-candle', up ? 'text-up' : 'text-down')}
              style={{ animationDelay: `${i * 110}ms`, transformOrigin: `${x}px ${(o + c) / 2}px` }}
            >
              <line x1={x} x2={x} y1={h} y2={l} stroke="currentColor" strokeWidth="1.2" />
              <rect x={x - 5} y={Math.min(o, c)} width="10" height={Math.max(2, Math.abs(o - c))} rx="1" fill="currentColor" />
            </g>
          )
        })}
        <path d={TREND} pathLength={1} fill="none" strokeWidth="2" strokeLinecap="round" className="insight-loader-trend stroke-accent" />
        <rect x="0" y="0" width="28" height="80" className="insight-loader-scan" />
      </svg>

      <div className="space-y-1">
        <p key={step} className="insight-loader-fade text-sm font-medium">
          <span className="insight-loader-dot me-2 inline-block h-2 w-2 rounded-full bg-accent align-middle" />
          {steps[step]}
        </p>
        <div className="mx-auto flex justify-center gap-1" aria-hidden="true">
          {steps.map((_, i) => (
            <span key={i} className={cx('h-1 w-6 rounded-full transition-colors duration-500', i <= step ? 'bg-accent' : 'bg-raised')} />
          ))}
        </div>
      </div>

      <p key={tip} className="insight-loader-fade max-w-md text-xs text-muted">
        <span className="font-medium text-accent-fg">Did you know? </span>
        {TIPS[tip]}
      </p>
    </div>
  )
}
