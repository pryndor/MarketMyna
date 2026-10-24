import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { cx } from '../lib/cx'
import { Button, Icon, Input } from './ui'

/* Excel-style column filters for table headers: a funnel button opens a
 * menu with sort A→Z / Z→A and a filter (checkbox list or min / max).
 * Changes apply on OK, like a spreadsheet. */

/** "10B", "2.5m", "500k", "1,200", "1e9", "50cr", "2L" -> number. */
function parseAmount(raw: string): number | undefined {
  const s = raw.trim().toLowerCase().replace(/[,\s₹$¥]/g, '').replace(/hk\$?/, '')
  if (!s) return undefined
  const m = s.match(/^(-?\d*\.?\d+(?:e-?\d+)?)(k|m|b|bn|t|cr|l|lakh|crore)?$/)
  if (!m) return undefined
  const mult: Record<string, number> = { k: 1e3, m: 1e6, b: 1e9, bn: 1e9, t: 1e12, cr: 1e7, crore: 1e7, l: 1e5, lakh: 1e5 }
  const n = Number(m[1]) * (m[2] ? mult[m[2]] : 1)
  return Number.isFinite(n) ? n : undefined
}

export function HeaderFilter({
  active,
  align = 'left',
  label,
  sortable,
  sorted,
  onSort,
  children,
}: {
  active: boolean
  align?: 'left' | 'right'
  label: string
  sortable?: boolean
  sorted?: 'asc' | 'desc' | null
  onSort?: (order: 'asc' | 'desc') => void
  children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <span ref={ref} className="relative inline-flex" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Filter ${label}`}
        aria-expanded={open}
        title={active ? `${label}: filtered` : `Filter ${label}`}
        className={cx(
          'rounded p-0.5 transition-colors',
          active ? 'bg-accent-soft text-accent-fg' : 'text-faint opacity-60 hover:bg-raised hover:text-fg hover:opacity-100',
          open && 'bg-raised text-fg opacity-100',
        )}
      >
        <Icon name="filter" className="h-3 w-3" />
      </button>
      {open && (
        <div
          className={cx(
            'absolute top-full z-30 mt-1 w-64 rounded-lg border border-line-strong bg-surface p-3 text-start text-sm font-normal normal-case text-fg shadow-card',
            align === 'right' ? 'end-0' : 'start-0',
          )}
        >
          {sortable && onSort && (
            <div className="mb-2 space-y-0.5 border-b border-line pb-2">
              {(['asc', 'desc'] as const).map((o) => (
                <button
                  key={o}
                  type="button"
                  onClick={() => {
                    onSort(o)
                    setOpen(false)
                  }}
                  className={cx(
                    'flex w-full items-center gap-2 rounded px-2 py-1 text-xs hover:bg-raised',
                    sorted === o ? 'text-accent-fg' : 'text-fg',
                  )}
                >
                  <Icon name="sort" className="h-3.5 w-3.5" />
                  {o === 'asc' ? 'Sort ascending (A → Z, low → high)' : 'Sort descending (Z → A, high → low)'}
                </button>
              ))}
            </div>
          )}
          {children(() => setOpen(false))}
        </div>
      )}
    </span>
  )
}

function Footer({ onClear, onApply, canApply = true }: { onClear: () => void; onApply: () => void; canApply?: boolean }) {
  return (
    <div className="mt-3 flex justify-end gap-2">
      <Button size="sm" variant="ghost" onClick={onClear}>
        Clear
      </Button>
      <Button size="sm" onClick={onApply} disabled={!canApply}>
        OK
      </Button>
    </div>
  )
}

/** Checkbox list with search and select-all, like Excel's value filter. */
export function ValuesFilter({
  options,
  selected,
  onApply,
  close,
}: {
  options: Array<{ value: string; label?: string; count?: number }>
  selected: string[]
  onApply: (values: string[]) => void
  close: () => void
}) {
  const [query, setQuery] = useState('')
  // Nothing selected = no filter = everything ticked.
  const [picked, setPicked] = useState<Set<string>>(() => new Set(selected.length ? selected : options.map((o) => o.value)))
  const shown = useMemo(
    () => options.filter((o) => (o.label ?? o.value).toLowerCase().includes(query.trim().toLowerCase())),
    [options, query],
  )
  const allShown = shown.length > 0 && shown.every((o) => picked.has(o.value))

  function toggleAll() {
    const next = new Set(picked)
    for (const o of shown) {
      if (allShown) next.delete(o.value)
      else next.add(o.value)
    }
    setPicked(next)
  }

  function apply() {
    const everything = options.every((o) => picked.has(o.value))
    onApply(everything ? [] : options.filter((o) => picked.has(o.value)).map((o) => o.value))
    close()
  }

  return (
    <div>
      {options.length > 8 && (
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search" className="mb-2 h-8 text-xs" autoFocus />
      )}
      <label className="flex cursor-pointer items-center gap-2 border-b border-line px-1 py-1 text-xs font-medium">
        <input type="checkbox" checked={allShown} onChange={toggleAll} className="accent-[var(--color-accent)]" />
        {query ? 'Select all results' : 'Select all'}
      </label>
      <div className="max-h-56 overflow-y-auto py-1">
        {shown.map((o) => (
          <label key={o.value} className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs hover:bg-raised">
            <input
              type="checkbox"
              checked={picked.has(o.value)}
              onChange={() => {
                const next = new Set(picked)
                if (next.has(o.value)) next.delete(o.value)
                else next.add(o.value)
                setPicked(next)
              }}
              className="accent-[var(--color-accent)]"
            />
            <span className="min-w-0 flex-1 truncate">{o.label ?? o.value}</span>
            {o.count != null && <span className="tabular text-faint">{o.count.toLocaleString()}</span>}
          </label>
        ))}
        {!shown.length && <p className="px-1 py-2 text-xs text-faint">No matches</p>}
      </div>
      <Footer
        onClear={() => {
          onApply([])
          close()
        }}
        onApply={apply}
        canApply={picked.size > 0}
      />
    </div>
  )
}

/** Min / max boxes (accepts 10B, 500k, 50cr, ...), plus optional presets. */
export function RangeFilter({
  min,
  max,
  onApply,
  close,
  unit,
  hint,
  presets = [],
  extra,
}: {
  min?: string | null
  max?: string | null
  onApply: (min: number | undefined, max: number | undefined) => void
  close: () => void
  unit?: string
  hint?: string
  presets?: Array<{ label: string; min?: number; max?: number }>
  extra?: ReactNode
}) {
  const [lo, setLo] = useState(min ?? '')
  const [hi, setHi] = useState(max ?? '')
  const loN = parseAmount(lo)
  const hiN = parseAmount(hi)
  const bad = (lo.trim() !== '' && loN === undefined) || (hi.trim() !== '' && hiN === undefined)

  return (
    <div>
      {extra}
      {presets.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1">
          {presets.map((p) => (
            <button
              key={p.label}
              type="button"
              onClick={() => {
                onApply(p.min, p.max)
                close()
              }}
              className="rounded-full border border-line px-2 py-0.5 text-xs text-muted hover:border-line-strong hover:text-fg"
            >
              {p.label}
            </button>
          ))}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-muted">
          Min{unit ? ` (${unit})` : ''}
          <Input value={lo} onChange={(e) => setLo(e.target.value)} placeholder="any" className="mt-1 h-8 text-xs" autoFocus />
        </label>
        <label className="text-xs text-muted">
          Max{unit ? ` (${unit})` : ''}
          <Input value={hi} onChange={(e) => setHi(e.target.value)} placeholder="any" className="mt-1 h-8 text-xs" />
        </label>
      </div>
      <p className={cx('mt-1.5 text-[11px]', bad ? 'text-down' : 'text-faint')}>
        {bad ? 'Use numbers like 500, 2.5k, 10M, 3B or 50cr' : (hint ?? 'Shorthand works: 500k, 10M, 3B, 50cr, 2L')}
      </p>
      <Footer
        onClear={() => {
          onApply(undefined, undefined)
          close()
        }}
        onApply={() => {
          onApply(loN, hiN)
          close()
        }}
        canApply={!bad}
      />
    </div>
  )
}

/** Single choice (radio list). */
export function ChoiceFilter({
  options,
  value,
  onApply,
  close,
}: {
  options: Array<{ value: string; label: string; hint?: string }>
  value: string
  onApply: (value: string) => void
  close: () => void
}) {
  return (
    <div className="space-y-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => {
            onApply(o.value)
            close()
          }}
          title={o.hint}
          className={cx('flex w-full items-center gap-2 rounded px-2 py-1 text-xs hover:bg-raised', value === o.value && 'text-accent-fg')}
        >
          <span className={cx('h-2 w-2 rounded-full border', value === o.value ? 'border-accent bg-accent' : 'border-line-strong')} />
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** "Contains" text box (Name column). */
export function TextFilter({ value, onApply, close }: { value: string; onApply: (v: string) => void; close: () => void }) {
  const [text, setText] = useState(value)
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        onApply(text.trim())
        close()
      }}
    >
      <label className="text-xs text-muted">
        Name or symbol contains
        <Input value={text} onChange={(e) => setText(e.target.value)} className="mt-1 h-8 text-xs" autoFocus />
      </label>
      <div className="mt-3 flex justify-end gap-2">
        <Button
          size="sm"
          variant="ghost"
          type="button"
          onClick={() => {
            onApply('')
            close()
          }}
        >
          Clear
        </Button>
        <Button size="sm" type="submit">
          OK
        </Button>
      </div>
    </form>
  )
}
