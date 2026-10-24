import { useCallback, useEffect, useState } from 'react'
import { getRisk, saveRiskSettings, type RiskSettings, type RiskStatus } from '../../api/trade'
import { cx } from '../../lib/cx'
import { errorMessage, num, price as fmtPrice } from '../../lib/format'
import { MARKETS } from '../../lib/options'
import { toast } from '../../lib/toast'
import { Alert, Badge, Button, Card, CardBody, CardHeader, EmptyState, Field, Input, Select, Skeleton, Switch } from '../ui'
import { CURRENCY } from './shared'

export default function RiskTab({ onStatus }: { onStatus?: (s: RiskStatus) => void }) {
  const [risk, setRisk] = useState<RiskStatus | null>(null)
  const [draft, setDraft] = useState<RiskSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(() => {
    getRisk()
      .then((r) => {
        setRisk(r)
        setDraft((d) => d ?? r.settings)
        setError(null)
        onStatus?.(r)
      })
      .catch((err) => setError(errorMessage(err)))
  }, [onStatus])

  useEffect(() => {
    load()
    const id = window.setInterval(load, 30_000)
    return () => window.clearInterval(id)
  }, [load])

  async function save() {
    if (!draft) return
    setSaving(true)
    try {
      const saved = await saveRiskSettings(draft)
      setDraft(saved)
      toast.success('Risk rules saved')
      load()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  if (error) return <Alert title="Risk status unavailable">{error}</Alert>
  if (!risk || !draft) return <Skeleton className="h-80 w-full" />
  const cur = CURRENCY[risk.settings.market]
  const set = (p: Partial<RiskSettings>) => setDraft((d) => (d ? { ...d, ...p } : d))
  const used = Math.min(100, risk.limit_used_pct ?? 0)

  return (
    <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
      <Card>
        <CardHeader title="Daily rules" description="Guard rails for your journal's trades. Nothing is blocked; you get a warning and one alert." />
        <CardBody className="space-y-3">
          <Field label="Market (currency) the rules cover">
            <Select options={MARKETS} value={draft.market} onChange={(e) => set({ market: e.target.value })} />
          </Field>
          <Field label={`Trading capital (${CURRENCY[draft.market] ?? ''})`}>
            <Input type="number" value={draft.capital} onChange={(e) => set({ capital: parseFloat(e.target.value) || 0 })} />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Daily loss limit %">
              <Input type="number" step="0.1" value={draft.daily_loss_limit_pct} onChange={(e) => set({ daily_loss_limit_pct: parseFloat(e.target.value) || 0 })} />
            </Field>
            <Field label="Max open risk %">
              <Input type="number" step="0.5" value={draft.max_open_risk_pct} onChange={(e) => set({ max_open_risk_pct: parseFloat(e.target.value) || 0 })} />
            </Field>
            <Field label="Max trades a day">
              <Input type="number" min="0" value={draft.max_trades_per_day} onChange={(e) => set({ max_trades_per_day: parseInt(e.target.value, 10) || 0 })} />
            </Field>
          </div>
          <Switch checked={draft.notify} onChange={(notify) => set({ notify })} label="Alert me when the limit is hit" description="Once a day, through your alert channels." />
          <Button onClick={save} loading={saving}>
            Save rules
          </Button>
        </CardBody>
      </Card>

      <div className="space-y-6">
        {risk.status === 'stop' ? (
          <Alert tone="warn" title="Stop trading for today">
            {risk.reasons[0]}
          </Alert>
        ) : risk.reasons.length ? (
          <Alert tone="accent" title="Heads up">
            <ul className="list-disc ps-4">
              {risk.reasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </Alert>
        ) : null}

        <Card>
          <CardHeader
            title="Today"
            description={`${MARKETS.find((m) => m.value === risk.settings.market)?.label ?? risk.settings.market} trades · refreshes every 30s`}
            actions={<Badge tone={risk.status === 'ok' ? 'up' : risk.status === 'warn' ? 'warn' : 'down'}>{risk.status === 'ok' ? 'Within limits' : risk.status === 'warn' ? 'Warning' : 'Limit hit'}</Badge>}
          />
          <CardBody className="space-y-4">
            <div>
              <div className="mb-1 flex justify-between text-xs text-muted">
                <span>Loss limit used</span>
                <span className="tabular">
                  {fmtPrice(Math.max(0, -risk.day_pnl), cur)} of {fmtPrice(risk.loss_limit, cur)}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-line">
                <div className={cx('h-full rounded-full', used >= 100 ? 'bg-down' : used >= 75 ? 'bg-warn' : 'bg-up')} style={{ width: `${used}%` }} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-4">
              <Tile label="Net P&L today" value={fmtPrice(risk.day_pnl, cur)} tone={risk.day_pnl >= 0 ? 'up' : 'down'} />
              <Tile label="Realised" value={fmtPrice(risk.realized, cur)} sub={`${risk.closed_today} closed`} />
              <Tile label="Open P&L" value={fmtPrice(risk.unrealized, cur)} />
              <Tile
                label="Open risk to stops"
                value={fmtPrice(risk.open_risk, cur)}
                sub={`${num(risk.open_risk_pct)}% of capital (cap ${risk.settings.max_open_risk_pct}%)`}
              />
              <Tile label="Trades today" value={`${risk.trades_today} / ${risk.settings.max_trades_per_day || '∞'}`} />
            </div>
          </CardBody>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader title="Open positions" />
          {risk.positions.length === 0 ? (
            <EmptyState icon="portfolio" title="No open trades" description="Open trades from the Journal show here with live P&L." />
          ) : (
            <table className="w-full text-sm">
              <thead className="border-y border-line text-xs text-muted">
                <tr>
                  <th className="px-4 py-2 text-start font-medium">Stock</th>
                  <th className="px-3 py-2 text-end font-medium">Qty</th>
                  <th className="px-3 py-2 text-end font-medium">Entry</th>
                  <th className="px-3 py-2 text-end font-medium">Now</th>
                  <th className="px-3 py-2 text-end font-medium">Stop</th>
                  <th className="px-4 py-2 text-end font-medium">P&amp;L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {risk.positions.map((p) => (
                  <tr key={p.id}>
                    <td className="px-4 py-2">
                      <span className="font-mono font-medium">{p.symbol}</span>
                      <span className={cx('ms-1.5 text-[12px] uppercase', p.side === 'short' ? 'text-down' : 'text-up')}>{p.side}</span>
                    </td>
                    <td className="tabular px-3 py-2 text-end">{num(p.quantity, p.quantity % 1 ? 4 : 0)}</td>
                    <td className="tabular px-3 py-2 text-end">{fmtPrice(p.entry_price, cur)}</td>
                    <td className="tabular px-3 py-2 text-end">{fmtPrice(p.price, cur)}</td>
                    <td className={cx('tabular px-3 py-2 text-end', p.stop == null && 'text-warn')}>{p.stop == null ? 'none' : fmtPrice(p.stop, cur)}</td>
                    <td className={cx('tabular px-4 py-2 text-end', (p.pnl ?? 0) >= 0 ? 'text-up' : 'text-down')}>{fmtPrice(p.pnl, cur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  )
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: 'up' | 'down' }) {
  return (
    <div className="bg-surface px-3 py-2.5">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx('tabular text-sm font-semibold', tone === 'up' && 'text-up', tone === 'down' && 'text-down')}>{value}</div>
      {sub && <div className="text-[12px] text-faint">{sub}</div>}
    </div>
  )
}
