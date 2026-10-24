import { useState } from 'react'
import { importFunds, parseCas, type CasPreview, type PortfolioSummary } from '../api/portfolio'
import { cx } from '../lib/cx'
import { toBase64 } from '../lib/files'
import { errorMessage, num } from '../lib/format'
import { toast } from '../lib/toast'
import { Button, Card, CardBody, CardHeader, Field, Input } from './ui'

const MAX_BYTES = 10 * 1024 * 1024

function inr(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
}

/** Upload a CAMS / KFintech CAS PDF, preview the funds, then sync units into the portfolio. */
export default function ImportCAS({
  portfolio,
  currency,
  onCancel,
  onImported,
}: {
  portfolio: string
  currency: string
  onCancel: () => void
  onImported: (s: PortfolioSummary) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [password, setPassword] = useState('')
  const [reading, setReading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [preview, setPreview] = useState<CasPreview | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)

  async function read() {
    if (!file) return
    if (file.size > MAX_BYTES) return setError('File is larger than 10 MB.')
    setReading(true)
    setError(null)
    try {
      const out = await parseCas(await toBase64(file), password)
      setPreview(out)
      setPicked(new Set(out.holdings.map((h) => h.amfi)))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setReading(false)
    }
  }

  async function save() {
    if (!preview) return
    setSaving(true)
    try {
      const rows = preview.holdings.filter((h) => picked.has(h.amfi))
      const res = await importFunds(
        portfolio,
        rows.map(({ amfi, scheme, units, nav, cost, date }) => ({ amfi, scheme, units, nav, cost, date })),
      )
      toast.success(
        res.applied
          ? `Updated ${res.applied} fund${res.applied === 1 ? '' : 's'}${res.unchanged ? `, ${res.unchanged} already in sync` : ''}`
          : 'Everything already in sync',
      )
      onImported(res.portfolio)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  const toggle = (code: string) =>
    setPicked((cur) => {
      const next = new Set(cur)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })

  return (
    <Card className="mb-6">
      <CardHeader
        title="Import mutual funds from CAS"
        description="Your Consolidated Account Statement (CAS) PDF, the one your mutual fund registrar emails you or lets you download."
        icon="plus"
      />
      <CardBody className="space-y-4">
        {!preview ? (
          <form
            className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_200px_auto] sm:items-end"
            onSubmit={(e) => {
              e.preventDefault()
              read()
            }}
          >
            <Field label="Statement PDF">
              <Input
                type="file"
                accept="application/pdf,.pdf"
                className="py-1.5"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </Field>
            <Field label="PDF password">
              <Input
                type="password"
                autoComplete="off"
                placeholder="Usually your PAN"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
              <Button type="submit" loading={reading} disabled={!file}>
                Read statement
              </Button>
            </div>
          </form>
        ) : (
          <>
            {currency !== 'INR' && (
              <p className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
                This portfolio is in {currency}; fund values are in INR and will be mixed without conversion.
              </p>
            )}
            {preview.holdings.length === 0 ? (
              <p className="text-sm text-muted">No fund holdings found in this statement.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="tabular w-full text-sm">
                  <thead className="text-xs text-muted">
                    <tr className="border-b border-line">
                      <th className="w-8 py-2" />
                      <th className="px-2 py-2 text-start font-medium">Scheme</th>
                      <th className="hidden px-2 py-2 text-end font-medium sm:table-cell">Units</th>
                      <th className="hidden px-2 py-2 text-end font-medium sm:table-cell">Cost</th>
                      <th className="px-2 py-2 text-end font-medium">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {preview.holdings.map((h) => (
                      <tr key={h.amfi} className={cx(!picked.has(h.amfi) && 'opacity-50')}>
                        <td className="py-2">
                          <input
                            type="checkbox"
                            className="h-4 w-4 accent-[var(--color-accent)]"
                            checked={picked.has(h.amfi)}
                            onChange={() => toggle(h.amfi)}
                            aria-label={`Import ${h.scheme}`}
                          />
                        </td>
                        <td className="max-w-[11rem] px-2 py-2 sm:max-w-72">
                          <div className="truncate" title={h.scheme}>{h.scheme}</div>
                          <div className="text-xs text-faint">
                            {h.amc} · {h.amfi}
                            {h.folios > 1 ? ` · ${h.folios} folios` : ''}
                            {h.units <= 0 ? ' · fully redeemed' : ''}
                          </div>
                          {h.units > 0 && <div className="text-xs text-muted sm:hidden">{num(h.units, 3)} units · cost {inr(h.cost)}</div>}
                        </td>
                        <td className="hidden px-2 py-2 text-end sm:table-cell">{num(h.units, 3)}</td>
                        <td className="hidden px-2 py-2 text-end text-muted sm:table-cell">{inr(h.cost)}</td>
                        <td className="px-2 py-2 text-end">{inr(h.value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {preview.skipped.length > 0 && (
              <p className="text-xs text-faint">
                Skipped: {preview.skipped.map((s) => `${s.scheme} (${s.reason})`).join('; ')}
              </p>
            )}
            <p className="text-xs text-faint">
              Units are synced: funds already in this portfolio only get the difference added or sold, so you can re-import
              each month. Funds without a cost in the statement are recorded at the statement NAV, so their gain starts at zero.
            </p>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm text-muted">
                Statement total <span className="tabular font-semibold text-fg">{inr(preview.total_value)}</span>
                {preview.statement_to ? ` as of ${preview.statement_to}` : ''}
              </span>
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => (setPreview(null), setError(null))}>
                  Back
                </Button>
                <Button icon="check" loading={saving} disabled={picked.size === 0} onClick={save}>
                  Import {picked.size} fund{picked.size === 1 ? '' : 's'}
                </Button>
              </div>
            </div>
          </>
        )}
        {error && <p className="text-sm text-down">{error}</p>}
        <p className="text-xs text-faint">The file and password are read in memory and not stored.</p>
      </CardBody>
    </Card>
  )
}
