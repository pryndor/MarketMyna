import { useEffect, useState } from 'react'
import {
  checkAlertsNow,
  createAlert,
  deleteAlert,
  getAlertKinds,
  getAlertMonitorStatus,
  listAlertEvents,
  updateAlert,
  type AlertEvent,
  type AlertKind,
  type AlertKindInfo,
  type PriceAlert,
} from '../../api/trade'
import { cx } from '../../lib/cx'
import { errorMessage, num, relativeTime, serverTime } from '../../lib/format'
import { MARKETS } from '../../lib/options'
import { toast } from '../../lib/toast'
import SymbolSearch from '../SymbolSearch'
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Field, Icon, Input, Select, StatusDot } from '../ui'

const DEFAULT_VALUE: Partial<Record<AlertKind, string>> = {
  pct_up: '3',
  pct_down: '3',
  rsi_above: '70',
  rsi_below: '30',
  volume_spike: '2',
  high_breakout: '20',
  low_breakdown: '20',
}

const UNIT_HINT: Record<string, string> = {
  price: 'Price',
  '%': 'Percent move today',
  rsi: 'RSI level (0–100)',
  'x avg': 'Multiple of the 20-day average volume',
  days: 'Look-back in trading days',
}

const STATUS_TONE = { active: 'up', paused: 'neutral', triggered: 'accent', expired: 'neutral' } as const

export default function AlertsTab({
  symbol,
  market,
  alerts,
  onChanged,
}: {
  symbol: string
  market: string
  alerts: PriceAlert[] | null
  onChanged: () => void
}) {
  const [kinds, setKinds] = useState<AlertKindInfo[]>([])
  const [events, setEvents] = useState<AlertEvent[]>([])
  const [monitor, setMonitor] = useState<{ running: boolean; poll_seconds: number | null } | null>(null)
  const [checking, setChecking] = useState(false)
  const [form, setForm] = useState({
    symbol,
    market,
    search: symbol,
    kind: 'price_above' as AlertKind,
    value: '',
    note: '',
    repeat: false,
    cooldown: '30',
  })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getAlertKinds().then(setKinds).catch(() => setKinds([]))
    getAlertMonitorStatus().then(setMonitor).catch(() => setMonitor(null))
  }, [])

  function loadEvents() {
    listAlertEvents(30)
      .then(setEvents)
      .catch(() => setEvents([]))
  }
  useEffect(loadEvents, [alerts])

  useEffect(() => {
    setForm((f) => ({ ...f, symbol, market, search: symbol }))
  }, [symbol, market])

  const kind = kinds.find((k) => k.kind === form.kind)

  async function submit() {
    const value = parseFloat(form.value)
    if (!form.symbol || !Number.isFinite(value)) return
    setSaving(true)
    try {
      await createAlert({
        symbol: form.symbol,
        market: form.market,
        kind: form.kind,
        value,
        note: form.note,
        repeat: form.repeat,
        cooldown_minutes: parseInt(form.cooldown, 10) || 0,
      })
      toast.success('Alert created')
      setForm((f) => ({ ...f, value: DEFAULT_VALUE[f.kind] ?? '', note: '' }))
      onChanged()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function act(fn: () => Promise<unknown>, done?: string) {
    try {
      await fn()
      if (done) toast.success(done)
      onChanged()
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  async function checkNow() {
    setChecking(true)
    try {
      const r = await checkAlertsNow()
      toast[r.fired.length ? 'success' : 'info'](
        r.fired.length ? `${r.fired.length} alert(s) fired: ${r.fired.map((f) => f.symbol).join(', ')}` : `Checked ${r.checked} alert(s); none fired`,
      )
      onChanged()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setChecking(false)
    }
  }

  const groups: Array<[string, PriceAlert[]]> = [
    ['Active', (alerts ?? []).filter((a) => a.status === 'active')],
    ['Paused', (alerts ?? []).filter((a) => a.status === 'paused')],
    ['Fired / expired', (alerts ?? []).filter((a) => a.status === 'triggered' || a.status === 'expired')],
  ]

  return (
    <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
      <div className="space-y-6">
        <Card>
          <CardHeader title="New alert" icon="bell" />
          <CardBody className="space-y-4">
            <div className="grid grid-cols-[minmax(0,1fr)_120px] gap-2">
              <Field label="Symbol">
                <SymbolSearch
                  value={form.search}
                  onChange={(search) => setForm((f) => ({ ...f, search, symbol: search.trim().toUpperCase() }))}
                  onSelect={(row) => setForm((f) => ({ ...f, symbol: row.symbol, market: row.market, search: row.symbol }))}
                  market={form.market}
                  placeholder="RELIANCE, AAPL…"
                />
              </Field>
              <Field label="Market">
                <Select options={MARKETS} value={form.market} onChange={(e) => setForm((f) => ({ ...f, market: e.target.value }))} />
              </Field>
            </div>
            <Field label="Condition">
              <Select
                options={kinds.map((k) => ({ value: k.kind, label: k.label }))}
                value={form.kind}
                onChange={(e) => {
                  const k = e.target.value as AlertKind
                  setForm((f) => ({ ...f, kind: k, value: DEFAULT_VALUE[k] ?? '' }))
                }}
              />
            </Field>
            <Field label={kind ? UNIT_HINT[kind.unit] : 'Value'}>
              <Input
                type="number"
                step="any"
                value={form.value}
                onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))}
                onKeyDown={(e) => e.key === 'Enter' && submit()}
              />
            </Field>
            <Field label="Note (sent with the alert)">
              <Input value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} placeholder="e.g. breakout entry, trail stop" />
            </Field>
            <label className="flex cursor-pointer items-start gap-3">
              <input
                type="checkbox"
                checked={form.repeat}
                onChange={(e) => setForm((f) => ({ ...f, repeat: e.target.checked }))}
                className="mt-0.5 h-4 w-4 accent-[var(--color-accent)]"
              />
              <span>
                <span className="block text-sm font-medium">Repeat</span>
                <span className="block text-xs text-muted">
                  Fire again each time the condition becomes true after clearing. Off = fire once.
                </span>
              </span>
            </label>
            {form.repeat && (
              <Field label="Minimum minutes between alerts">
                <Input type="number" min="0" value={form.cooldown} onChange={(e) => setForm((f) => ({ ...f, cooldown: e.target.value }))} className="w-28" />
              </Field>
            )}
            <Button onClick={submit} loading={saving} disabled={!form.symbol || !form.value} icon="plus">
              Create alert
            </Button>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Monitor" />
          <CardBody className="space-y-3 text-xs text-muted">
            <div className="flex items-center gap-2 text-sm text-fg">
              <StatusDot tone={monitor?.running ? 'up' : 'down'} />
              {monitor?.running ? `Checking every ${monitor.poll_seconds}s while each market is open` : 'Not running (start the API server)'}
            </div>
            <p>
              Alerts go to the channels routed for <b className="text-fg">alerts</b> under Settings → Notifications
              (Telegram, push, …). Crypto is checked around the clock.
            </p>
            <Button size="sm" variant="secondary" icon="refresh" loading={checking} onClick={checkNow}>
              Check now (ignores market hours)
            </Button>
          </CardBody>
        </Card>
      </div>

      <div className="space-y-6">
        <Card>
          <CardHeader title="Your alerts" description={alerts ? `${alerts.length} total` : undefined} />
          {alerts && alerts.length === 0 ? (
            <EmptyState icon="bell" title="No alerts yet" description="Create one here or click a price on the chart." />
          ) : (
            groups
              .filter(([, list]) => list.length)
              .map(([title, list]) => (
                <div key={title}>
                  <div className="border-t border-line bg-canvas/40 px-5 py-1.5 text-xs font-medium text-muted">{title}</div>
                  <ul className="divide-y divide-line">
                    {list.map((a) => (
                      <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-2.5 text-sm">
                        <span className="w-24 font-mono font-medium">{a.symbol}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block">{a.description}</span>
                          <span className="block text-xs text-muted">
                            {a.note && `${a.note} · `}
                            {a.repeat ? 'repeats' : 'once'}
                            {a.last_value != null && ` · now ${num(a.last_value)}`}
                            {a.last_triggered_at && ` · fired ${relativeTime(a.last_triggered_at)}`}
                            {a.trigger_count > 1 && ` (${a.trigger_count}×)`}
                          </span>
                        </span>
                        <Badge tone={STATUS_TONE[a.status]}>{a.status}</Badge>
                        <div className="flex gap-1">
                          {a.status === 'active' ? (
                            <Button size="sm" variant="ghost" onClick={() => act(() => updateAlert(a.id, { status: 'paused' }))}>
                              Pause
                            </Button>
                          ) : (
                            <Button size="sm" variant="ghost" onClick={() => act(() => updateAlert(a.id, { status: 'active' }), 'Alert armed')}>
                              {a.status === 'paused' ? 'Resume' : 'Re-arm'}
                            </Button>
                          )}
                          <button
                            type="button"
                            onClick={() => act(() => deleteAlert(a.id))}
                            className="rounded-md p-1.5 text-faint hover:bg-down-soft hover:text-down"
                            aria-label={`Delete alert for ${a.symbol}`}
                          >
                            <Icon name="trash" />
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              ))
          )}
        </Card>

        <Card>
          <CardHeader title="Recent triggers" />
          {events.length === 0 ? (
            <CardBody>
              <p className="text-xs text-muted">Fired alerts appear here with where they were sent.</p>
            </CardBody>
          ) : (
            <ul className="divide-y divide-line">
              {events.map((e) => {
                const sent = Object.entries(e.delivery ?? {})
                return (
                  <li key={e.id} className="px-5 py-2.5 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-mono font-medium">{e.symbol}</span>
                      <span className="text-xs text-muted">{serverTime(e.created_at).toLocaleString()}</span>
                    </div>
                    <pre className="mt-1 font-sans text-xs whitespace-pre-wrap text-muted">{e.message}</pre>
                    <div className="mt-1 flex flex-wrap gap-2 text-[12px]">
                      {sent.length === 0 ? (
                        <span className="text-warn">No alert channel configured</span>
                      ) : (
                        sent.map(([ch, ok]) => (
                          <span key={ch} className={cx(ok ? 'text-up' : 'text-down')}>
                            {ok ? '✓' : '✗'} {ch}
                          </span>
                        ))
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
