import { useState } from 'react'
import {
  createCustomEvent,
  createEventAlert,
  deleteCustomEvent,
  deleteEventAlert,
  sendEventAlert,
  sentMessage,
  updateEventAlert,
  type AlertPatch,
  type CustomEvent,
  type EventAlert,
  type EventList,
  type EventSymbol,
  type EventType,
  type Repeat,
} from '../api/calendar'
import { cx } from '../lib/cx'
import { errorMessage } from '../lib/format'
import { toast } from '../lib/toast'
import SymbolSearch from './SymbolSearch'
import { Button, Field, Icon, Input, Select, Switch } from './ui'

export const LEAD_OPTIONS = [0, 1, 2, 3, 7].map((d) => ({
  value: String(d),
  label: d === 0 ? 'Same day' : d === 1 ? '1 day before' : `${d} days before`,
}))
export const HOUR_OPTIONS = Array.from({ length: 24 }, (_, h) => ({ value: String(h), label: `${String(h).padStart(2, '0')}:00` }))

const REPEAT_OPTIONS = [
  { value: 'none', label: 'Once' },
  { value: 'monthly', label: 'Every month' },
  { value: 'yearly', label: 'Every year' },
]

const symKey = (s: EventSymbol) => `${s.symbol}:${s.market}`

/** Which watchlists / portfolios count, plus stocks added just for events. */
export function StockPicker({
  lists,
  sources,
  symbols,
  onChange,
}: {
  lists: EventList[]
  /** null = every list */
  sources: string[] | null
  symbols: EventSymbol[]
  onChange: (next: { sources: string[] | null; symbols: EventSymbol[] }) => void
}) {
  const [query, setQuery] = useState('')
  const all = sources === null
  const chosen = new Set(sources ?? lists.map((l) => l.id))

  function toggleList(id: string) {
    const next = new Set(chosen)
    if (!next.delete(id)) next.add(id)
    const ids = lists.map((l) => l.id).filter((x) => next.has(x))
    onChange({ sources: ids.length === lists.length && lists.length > 0 ? null : ids, symbols })
  }

  function add(symbol: string, market: string) {
    const s = { symbol: symbol.trim().toUpperCase(), market: market || 'us' }
    if (!s.symbol || symbols.some((x) => symKey(x) === symKey(s))) return
    onChange({ sources, symbols: [...symbols, s] })
    setQuery('')
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-faint">Watchlists &amp; portfolios</span>
          {lists.length > 0 && (
            <button
              type="button"
              className="text-xs text-accent hover:underline"
              onClick={() => onChange({ sources: all ? [] : null, symbols })}
            >
              {all ? 'Clear all' : 'Use all lists'}
            </button>
          )}
        </div>
        {lists.length === 0 ? (
          <p className="text-xs text-muted">No watchlists or portfolios yet. Add stocks below instead.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {lists.map((l) => (
              <label
                key={l.id}
                className={cx(
                  'inline-flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1 text-sm',
                  chosen.has(l.id) ? 'border-accent/50 bg-accent-soft' : 'border-line',
                )}
              >
                <input type="checkbox" className="accent-accent" checked={chosen.has(l.id)} onChange={() => toggleList(l.id)} />
                <Icon name={l.kind === 'portfolio' ? 'portfolio' : 'star'} className="h-3.5 w-3.5 text-muted" />
                {l.name}
                <span className="text-xs text-faint">{l.count}</span>
              </label>
            ))}
          </div>
        )}
      </div>
      <div>
        <span className="mb-2 block text-xs font-semibold uppercase tracking-wide text-faint">Extra stocks</span>
        <SymbolSearch
          value={query}
          onChange={setQuery}
          type="stock"
          exclude={symbols.map((s) => s.symbol)}
          placeholder="Add a stock just for events, e.g. INFY"
          onSelect={(row) => add(row.symbol, row.market)}
          onSubmit={() => add(query, 'us')}
          className="max-w-md"
        />
        {symbols.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {symbols.map((s) => (
              <span key={symKey(s)} className="inline-flex items-center gap-1 rounded-md border border-line bg-raised px-2 py-0.5 text-xs">
                <span className="font-mono">{s.symbol}</span>
                <span className="text-faint">{s.market === 'india' ? 'IN' : s.market.toUpperCase()}</span>
                <button
                  type="button"
                  aria-label={`Remove ${s.symbol}`}
                  className="text-faint hover:text-down"
                  onClick={() => onChange({ sources, symbols: symbols.filter((x) => symKey(x) !== symKey(s)) })}
                >
                  <Icon name="x" className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/** Add / remove the user's own dated items. */
export function MyEventsPanel({ events, onChanged }: { events: CustomEvent[]; onChanged: () => void }) {
  const [title, setTitle] = useState('')
  const [date, setDate] = useState('')
  const [repeat, setRepeat] = useState<Repeat>('none')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)

  async function add() {
    if (!title.trim() || !date) {
      toast.error('Give the event a name and a date')
      return
    }
    setSaving(true)
    try {
      await createCustomEvent({ title: title.trim(), date, repeat, note: note.trim() })
      setTitle('')
      setNote('')
      setRepeat('none')
      toast.success('Event added')
      onChanged()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function remove(e: CustomEvent) {
    try {
      await deleteCustomEvent(e.id)
      toast.success(`Removed "${e.title}"`)
      onChanged()
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_10rem_9rem_minmax(0,2fr)_auto] lg:items-end">
        <Field label="What">
          <Input value={title} maxLength={120} placeholder="SIP debit, IPO listing, AGM…" onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Date">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label="Repeats">
          <Select value={repeat} onChange={(e) => setRepeat(e.target.value as Repeat)} options={REPEAT_OPTIONS} />
        </Field>
        <Field label="Note (optional)">
          <Input value={note} maxLength={500} placeholder="₹5,000 into Parag Parikh Flexi Cap" onChange={(e) => setNote(e.target.value)} />
        </Field>
        <Button icon="plus" loading={saving} onClick={add}>
          Add
        </Button>
      </div>
      {events.length > 0 && (
        <ul className="divide-y divide-line rounded-md border border-line">
          {events.map((e) => (
            <li key={e.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="font-medium">{e.title}</span>
                <span className="text-xs text-muted">
                  {' '}
                  · {e.date}
                  {e.repeat !== 'none' && ` · every ${e.repeat === 'monthly' ? 'month' : 'year'}`}
                </span>
                {e.note && <span className="block truncate text-xs text-faint">{e.note}</span>}
              </span>
              <Button variant="ghost" size="sm" icon="trash" aria-label={`Remove ${e.title}`} onClick={() => remove(e)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function describe(a: EventAlert, lists: EventList[], types: EventType[]): string {
  const src =
    a.sources === null
      ? 'All lists'
      : a.sources.length
        ? lists.filter((l) => a.sources!.includes(l.id)).map((l) => l.name).join(', ') || 'No lists'
        : ''
  const stocks = a.symbols.length ? `${a.symbols.length} stock${a.symbols.length === 1 ? '' : 's'}` : ''
  const what = [src, stocks].filter(Boolean).join(' + ') || 'No stocks (economy / own events only)'
  const kinds =
    a.event_types === null
      ? 'all events'
      : types.filter((t) => a.event_types!.includes(t.key)).map((t) => t.name).join(', ') || 'no event types'
  const when = LEAD_OPTIONS.find((o) => o.value === String(a.days_before))?.label ?? `${a.days_before} days before`
  return `${what} · ${kinds} · ${when.toLowerCase()} at ${String(a.notify_hour).padStart(2, '0')}:00`
}

function AlertEditor({
  initial,
  lists,
  types,
  onSave,
  onCancel,
}: {
  initial: EventAlert | null
  lists: EventList[]
  types: EventType[]
  onSave: (patch: AlertPatch) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [sources, setSources] = useState<string[] | null>(initial ? initial.sources : null)
  const [symbols, setSymbols] = useState<EventSymbol[]>(initial?.symbols ?? [])
  const [chosen, setChosen] = useState<Set<string>>(new Set(initial?.event_types ?? types.map((t) => t.key)))
  const [days, setDays] = useState(String(initial?.days_before ?? 1))
  const [hour, setHour] = useState(String(initial?.notify_hour ?? 8))
  const [saving, setSaving] = useState(false)

  const toggle = (key: string) =>
    setChosen((prev) => {
      const next = new Set(prev)
      if (!next.delete(key)) next.add(key)
      return next
    })

  async function save() {
    if (!name.trim()) {
      toast.error('Name the alert, e.g. "US tech earnings"')
      return
    }
    const everyType = types.every((t) => chosen.has(t.key))
    setSaving(true)
    try {
      await onSave({
        name: name.trim(),
        ...(sources === null ? { all_lists: true } : { sources }),
        symbols,
        ...(everyType ? { all_types: true } : { event_types: [...chosen] }),
        days_before: Number(days),
        notify_hour: Number(hour),
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4 rounded-lg border border-line-strong bg-canvas/40 p-4">
      <Field label="Alert name" className="max-w-sm">
        <Input value={name} maxLength={80} placeholder="US tech earnings" onChange={(e) => setName(e.target.value)} />
      </Field>
      <StockPicker
        lists={lists}
        sources={sources}
        symbols={symbols}
        onChange={(n) => {
          setSources(n.sources)
          setSymbols(n.symbols)
        }}
      />
      <div>
        <span className="mb-2 block text-xs font-semibold uppercase tracking-wide text-faint">Events in this alert</span>
        <div className="flex flex-wrap gap-1.5">
          {types.map((t) => (
            <button
              key={t.key}
              type="button"
              title={t.about}
              aria-pressed={chosen.has(t.key)}
              onClick={() => toggle(t.key)}
              className={cx(
                'rounded-md border px-2 py-1 text-xs',
                chosen.has(t.key) ? 'border-accent/50 bg-accent-soft text-fg' : 'border-line text-muted hover:text-fg',
              )}
            >
              {t.name}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <Select className="w-auto" value={days} onChange={(e) => setDays(e.target.value)} options={LEAD_OPTIONS} />
        <span className="text-muted">at</span>
        <Select className="w-auto" value={hour} onChange={(e) => setHour(e.target.value)} options={HOUR_OPTIONS} />
      </div>
      <div className="flex flex-wrap gap-2">
        <Button icon="check" loading={saving} onClick={save}>
          {initial ? 'Save alert' : 'Create alert'}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

/** Named alerts: each its own stocks, event types and time; everything in one message. */
export function EventAlerts({
  alerts,
  lists,
  types,
  onChanged,
}: {
  alerts: EventAlert[]
  lists: EventList[]
  types: EventType[]
  onChanged: () => void
}) {
  const [editing, setEditing] = useState<number | 'new' | null>(null)
  const [busy, setBusy] = useState<number | null>(null)

  async function run(fn: () => Promise<unknown>, done?: string) {
    try {
      await fn()
      if (done) toast.success(done)
      onChanged()
      return true
    } catch (err) {
      toast.error(errorMessage(err))
      return false
    }
  }

  async function sendNow(a: EventAlert) {
    setBusy(a.id)
    try {
      const res = await sendEventAlert(a.id)
      if (!res.sent) toast.info(`Nothing due in "${a.name}" right now`)
      else {
        const m = sentMessage(res)
        toast[m.tone](m.text)
      }
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium">Event alerts</div>
          <div className="text-xs text-muted">
            Group stocks and event types into your own alerts. Each alert sends everything it finds in one message, at its own time.
          </div>
        </div>
        {editing !== 'new' && (
          <Button variant="secondary" size="sm" icon="plus" onClick={() => setEditing('new')}>
            New alert
          </Button>
        )}
      </div>
      {editing === 'new' && (
        <AlertEditor
          initial={null}
          lists={lists}
          types={types}
          onCancel={() => setEditing(null)}
          onSave={async (patch) => {
            if (await run(() => createEventAlert(patch), 'Alert created')) setEditing(null)
          }}
        />
      )}
      {alerts.map((a) =>
        editing === a.id ? (
          <AlertEditor
            key={a.id}
            initial={a}
            lists={lists}
            types={types}
            onCancel={() => setEditing(null)}
            onSave={async (patch) => {
              if (await run(() => updateEventAlert(a.id, patch), 'Alert saved')) setEditing(null)
            }}
          />
        ) : (
          <div key={a.id} className="flex flex-col gap-2 rounded-lg border border-line px-3 py-2.5 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 flex-1">
              <div className={cx('text-sm font-medium', !a.enabled && 'text-muted')}>{a.name}</div>
              <div className="text-xs text-muted">{describe(a, lists, types)}</div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button variant="ghost" size="sm" icon="send" loading={busy === a.id} onClick={() => sendNow(a)} aria-label={`Send ${a.name} now`} />
              <Button variant="ghost" size="sm" icon="pencil" onClick={() => setEditing(a.id)} aria-label={`Edit ${a.name}`} />
              <Button variant="ghost" size="sm" icon="trash" onClick={() => run(() => deleteEventAlert(a.id), `Deleted "${a.name}"`)} aria-label={`Delete ${a.name}`} />
              <div className="ms-1 w-9">
                <Switch checked={a.enabled} onChange={(enabled) => run(() => updateEventAlert(a.id, { enabled }))} label="" />
              </div>
            </div>
          </div>
        ),
      )}
    </div>
  )
}
