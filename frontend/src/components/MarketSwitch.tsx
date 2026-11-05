import { useEffect, useId, useRef, useState } from 'react'
import { cx } from '../lib/cx'
import type { Option } from '../lib/options'
import { Icon } from './ui'

// The Markets page's market tabs. The last tab ("All markets") opens a
// searchable list: every market in one list, or one more market (Canada,
// UK, ...) that has no tab of its own. Looks like the Segmented control.

export default function MarketSwitch({
  tabs,
  allValue,
  more,
  value,
  onChange,
  everyLabel,
  pickedNote,
  searchPlaceholder,
  noMatch,
}: {
  /** The tabs before "All markets". */
  tabs: Option[]
  /** "All markets" itself (value 'all'). */
  allValue: Option
  /** Markets reachable only through the "All markets" list. */
  more: Option[]
  value: string
  onChange: (value: string) => void
  everyLabel: string
  /** Said after a picked market's exchange name under the tabs. */
  pickedNote: string
  searchPlaceholder: string
  noMatch: string
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [active, setActive] = useState(0)
  const ref = useRef<HTMLDivElement>(null)
  const listId = useId()

  const picked = more.find((m) => m.value === value)
  const allActive = value === allValue.value || Boolean(picked)
  // "Every market" is matched on its name only (its hint lists the tab markets).
  const choices: Option[] = [{ value: allValue.value, label: everyLabel }, ...more]
  const needle = text.trim().toLowerCase()
  // Match the start of any word in the market or exchange name: "is" finds
  // Israel, "lon" finds the London Stock Exchange.
  const shown = needle
    ? choices.filter((o) => `${o.label} ${o.hint ?? ''}`.toLowerCase().split(/[^\p{L}\p{N}]+/u).some((w) => w.startsWith(needle)))
    : choices
  const activeTab = tabs.find((o) => o.value === value)
  const hint = picked ? `${picked.hint} · ${pickedNote}` : allActive ? allValue.hint : activeTab?.hint

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  function pick(v: string) {
    setOpen(false)
    setText('')
    if (v !== value) onChange(v)
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === 'Escape') setOpen(false)
    else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => Math.min(a + 1, shown.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter' && shown[active]) {
      e.preventDefault()
      pick(shown[active].value)
    }
  }

  const tabClass = (on: boolean) =>
    cx(
      'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
      on ? 'cursor-default bg-raised text-fg shadow-sm ring-1 ring-line-strong' : 'cursor-pointer text-muted hover:text-fg',
    )

  return (
    <div>
      <div ref={ref} className="relative inline-flex flex-wrap gap-1 rounded-lg border border-line bg-canvas p-1">
        {tabs.map((o) => (
          <button key={o.value} type="button" title={o.hint} aria-pressed={o.value === value} onClick={() => pick(o.value)} className={tabClass(o.value === value)}>
            {o.label}
          </button>
        ))}
        <button
          type="button"
          title={allValue.hint}
          aria-pressed={allActive}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          onClick={() => {
            setActive(0)
            setOpen((v) => !v)
          }}
          className={cx(tabClass(allActive), 'cursor-pointer')}
        >
          {allValue.label}
          {picked && <span className="rounded bg-accent-soft px-1.5 py-0.5 text-[11px] font-semibold leading-none text-accent-fg">{picked.label}</span>}
          <Icon name="chevron" className={cx('h-3.5 w-3.5 transition-transform', open ? '-rotate-90' : 'rotate-90')} />
        </button>

        {open && (
          <div className="absolute end-0 top-full z-30 mt-1.5 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-line bg-surface p-2 shadow-card">
            <div className="relative">
              <Icon name="search" className="pointer-events-none absolute start-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" />
              <input
                autoFocus
                value={text}
                onChange={(e) => {
                  setText(e.target.value)
                  setActive(0)
                }}
                onKeyDown={onKey}
                placeholder={searchPlaceholder}
                spellCheck={false}
                className="h-9 w-full rounded-md border border-line bg-canvas ps-8 pe-3 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent-soft"
              />
            </div>
            <ul id={listId} role="listbox" className="mt-1.5 max-h-72 overflow-y-auto">
              {shown.length === 0 && <li className="px-2.5 py-2 text-sm text-muted">{noMatch}</li>}
              {shown.map((o, i) => {
                const selected = o.value === value || (o.value === allValue.value && value === allValue.value)
                return (
                  <li key={o.value} role="option" aria-selected={selected}>
                    <button
                      type="button"
                      onMouseEnter={() => setActive(i)}
                      onClick={() => pick(o.value)}
                      className={cx(
                        'flex w-full items-start justify-between gap-2 rounded-md px-2.5 py-1.5 text-start',
                        i === active ? 'bg-raised' : '',
                      )}
                    >
                      <span className="min-w-0">
                        <span className="block text-sm text-fg">{o.label}</span>
                        {o.hint && <span className="block truncate text-xs text-faint">{o.hint}</span>}
                      </span>
                      {selected && <Icon name="check" className="mt-0.5 h-4 w-4 shrink-0 text-accent" />}
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
      {hint && <p className="mt-1.5 text-xs text-faint">{hint}</p>}
    </div>
  )
}
