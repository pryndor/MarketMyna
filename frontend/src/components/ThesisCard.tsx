import { useEffect, useState } from 'react'
import {
  addThesisLog,
  deleteThesis,
  getThesis,
  markThesisReviewed,
  saveThesis,
  type Conviction,
  type Impact,
  type PillarStatus,
  type Thesis,
  type ThesisPatch,
} from '../api/thesis'
import { cx } from '../lib/cx'
import { errorMessage, num } from '../lib/format'
import { toast } from '../lib/toast'
import { Button, Card, CardBody, CardHeader, Field, Input, Segmented, Select, Skeleton, Textarea } from './ui'

const STATUS: Record<PillarStatus, { label: string; className: string }> = {
  on_track: { label: 'On track', className: 'bg-up-soft text-up' },
  watch: { label: 'Watch', className: 'bg-warn-soft text-warn' },
  broken: { label: 'Broken', className: 'bg-down-soft text-down' },
}
const NEXT_STATUS: Record<PillarStatus, PillarStatus> = { on_track: 'watch', watch: 'broken', broken: 'on_track' }
const TONE = { up: 'text-up', down: 'text-down', warn: 'text-warn', info: 'text-muted' }
const IMPACT: Record<Impact, string> = { strengthens: 'Strengthens', weakens: 'Weakens', neutral: 'Neutral' }
const CONVICTIONS = [
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
]

type Draft = { statement: string; pillars: { text: string; status: PillarStatus }[]; risks: string[]; exit: string; exitNote: string; target: string; conviction: Conviction }

function draftOf(t: Thesis | null): Draft {
  return {
    statement: t?.statement ?? '',
    pillars: t?.pillars.length ? t.pillars : [{ text: '', status: 'on_track' }],
    risks: t?.risks.length ? t.risks : [''],
    exit: t?.exit_below != null ? String(t.exit_below) : '',
    exitNote: t?.exit_note ?? '',
    target: t?.target != null ? String(t.target) : '',
    conviction: t?.conviction ?? 'medium',
  }
}

function Editor({ initial, onSave, onCancel }: { initial: Thesis | null; onSave: (p: ThesisPatch) => Promise<void>; onCancel: () => void }) {
  const [d, setD] = useState<Draft>(() => draftOf(initial))
  const [saving, setSaving] = useState(false)
  const set = (patch: Partial<Draft>) => setD((prev) => ({ ...prev, ...patch }))

  async function save() {
    const exit = d.exit.trim() ? Number(d.exit) : null
    const target = d.target.trim() ? Number(d.target) : null
    setSaving(true)
    try {
      await onSave({
        statement: d.statement,
        pillars: d.pillars.filter((p) => p.text.trim()),
        risks: d.risks.filter((r) => r.trim()),
        exit_note: d.exitNote,
        conviction: d.conviction,
        ...(exit != null ? { exit_below: exit } : { clear_exit: true }),
        ...(target != null ? { target } : { clear_target: true }),
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <Field label="Thesis" hint="One or two sentences that could be proved wrong, e.g. “Margins expand as the mix shifts to software”.">
        <Textarea className="font-sans text-sm" rows={2} maxLength={2000} value={d.statement} onChange={(e) => set({ statement: e.target.value })} />
      </Field>
      <div>
        <span className="mb-1.5 block text-xs font-medium text-muted">Pillars: what has to go right (up to 5)</span>
        <div className="space-y-2">
          {d.pillars.map((p, i) => (
            <div key={i} className="flex gap-2">
              <Input value={p.text} maxLength={300} placeholder="Revenue growth above 20%" onChange={(e) => set({ pillars: d.pillars.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)) })} />
              <Select
                className="w-32"
                value={p.status}
                onChange={(e) => set({ pillars: d.pillars.map((x, j) => (j === i ? { ...x, status: e.target.value as PillarStatus } : x)) })}
                options={Object.entries(STATUS).map(([value, s]) => ({ value, label: s.label }))}
              />
            </div>
          ))}
          {d.pillars.length < 5 && (
            <Button size="sm" variant="ghost" icon="plus" onClick={() => set({ pillars: [...d.pillars, { text: '', status: 'on_track' }] })}>
              Add pillar
            </Button>
          )}
        </div>
      </div>
      <div>
        <span className="mb-1.5 block text-xs font-medium text-muted">Risks: what would prove it wrong (up to 5)</span>
        <div className="space-y-2">
          {d.risks.map((r, i) => (
            <Input key={i} value={r} maxLength={300} placeholder="A price war with the market leader" onChange={(e) => set({ risks: d.risks.map((x, j) => (j === i ? e.target.value : x)) })} />
          ))}
          {d.risks.length < 5 && (
            <Button size="sm" variant="ghost" icon="plus" onClick={() => set({ risks: [...d.risks, ''] })}>
              Add risk
            </Button>
          )}
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Exit if the price falls below" hint="Optional: you get a message">
          <Input type="number" min="0" step="any" value={d.exit} onChange={(e) => set({ exit: e.target.value })} />
        </Field>
        <Field label="Worth if it plays out (target)" hint="Optional: you get a message">
          <Input type="number" min="0" step="any" value={d.target} onChange={(e) => set({ target: e.target.value })} />
        </Field>
        <Field label="Conviction">
          <Segmented size="sm" value={d.conviction} onChange={(v) => set({ conviction: v as Conviction })} options={CONVICTIONS} />
        </Field>
      </div>
      <Field label="Anything else that would make you exit" hint="Optional">
        <Input value={d.exitNote} maxLength={500} placeholder="Management change, a dilutive deal, losing the top customer…" onChange={(e) => set({ exitNote: e.target.value })} />
      </Field>
      <div className="flex gap-2">
        <Button icon="check" loading={saving} disabled={!d.statement.trim()} onClick={save}>
          Save thesis
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

/** Your reason for owning a stock, its pillars and risks, exit / target levels,
 * an update log, and a check against live data (thesis-tracker workflow). */
export default function ThesisCard({ symbol, market }: { symbol: string; market: string }) {
  const [thesis, setThesis] = useState<Thesis | null | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState('')
  const [impact, setImpact] = useState<Impact>('neutral')
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    let live = true
    setThesis(undefined)
    setError(null)
    setEditing(false)
    getThesis(symbol, market)
      .then((t) => live && setThesis(t))
      .catch((err) => live && setError(errorMessage(err)))
    return () => {
      live = false
    }
  }, [symbol, market])

  async function run(fn: () => Promise<Thesis>, done?: string) {
    setBusy(true)
    try {
      setThesis(await fn())
      if (done) toast.success(done)
      return true
    } catch (err) {
      toast.error(errorMessage(err))
      return false
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!thesis) return
    try {
      await deleteThesis(thesis.id)
      setThesis(null)
      setConfirming(false)
      toast.success('Thesis deleted')
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  const t = thesis
  return (
    <Card id="section-thesis" section="My thesis">
      <CardHeader
        title="My thesis"
        icon="pencil"
        description={t ? `Conviction ${t.conviction} · last reviewed ${t.reviewed_at ?? '—'}` : 'Why you own or watch this stock, and what would prove you wrong'}
      />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-sm text-muted">Thesis unavailable: {error}</p>
        ) : t === undefined ? (
          <Skeleton className="h-24 w-full" />
        ) : editing || t === null ? (
          editing ? (
            <Editor
              initial={t}
              onCancel={() => setEditing(false)}
              onSave={async (patch) => {
                if (await run(() => saveThesis(symbol, market, patch), 'Thesis saved')) setEditing(false)
              }}
            />
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="max-w-xl text-sm text-muted">
                Write down why you own (or are watching) {symbol}: what has to go right, what would prove you wrong, and the price that breaks it.
                MarketMyna checks it against live data and reminds you to review it every quarter.
              </p>
              <Button icon="pencil" onClick={() => setEditing(true)}>
                Write a thesis
              </Button>
            </div>
          )
        ) : (
          <>
            <p className="text-sm font-medium">{t.statement}</p>

            {t.signals && t.signals.length > 0 && (
              <ul className="space-y-1 rounded-lg bg-canvas p-3 text-sm">
                {t.signals.map((s) => (
                  <li key={s.key} className={cx('flex gap-2', TONE[s.tone])}>
                    <span>•</span>
                    <span>{s.text}</span>
                  </li>
                ))}
              </ul>
            )}

            {t.pillars.length > 0 && (
              <div>
                <div className="mb-2 text-xs font-medium text-muted">Pillars (click a status to change it)</div>
                <ul className="space-y-1.5">
                  {t.pillars.map((p, i) => (
                    <li key={i} className="flex items-center justify-between gap-3 text-sm">
                      <span>{p.text}</span>
                      <button
                        type="button"
                        disabled={busy}
                        className={cx('shrink-0 rounded px-2 py-0.5 text-xs', STATUS[p.status].className)}
                        onClick={() =>
                          run(() => saveThesis(symbol, market, { pillars: t.pillars.map((x, j) => (j === i ? { ...x, status: NEXT_STATUS[x.status] } : x)) }))
                        }
                      >
                        {STATUS[p.status].label}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              {t.risks.length > 0 && (
                <div>
                  <div className="mb-1 text-xs font-medium text-muted">Risks</div>
                  <ul className="list-inside list-disc space-y-0.5 text-sm">
                    {t.risks.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="tabular space-y-0.5 text-sm">
                <div className="text-xs font-medium text-muted">Levels</div>
                {t.price != null && <div>Price now {num(t.price, 2)}</div>}
                <div>Exit below {t.exit_below != null ? num(t.exit_below, 2) : '—'}</div>
                <div>Target {t.target != null ? num(t.target, 2) : '—'}</div>
                {t.exit_note && <div className="text-xs text-muted">Also exit if: {t.exit_note}</div>}
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-xs font-medium text-muted">Update log</div>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input value={note} maxLength={1000} placeholder="What happened? (results, management change, a competitor move…)" onChange={(e) => setNote(e.target.value)} />
                <Select className="sm:w-40" value={impact} onChange={(e) => setImpact(e.target.value as Impact)} options={Object.entries(IMPACT).map(([value, label]) => ({ value, label }))} />
                <Button
                  disabled={!note.trim()}
                  loading={busy}
                  onClick={async () => {
                    if (await run(() => addThesisLog(t.id, note, impact), 'Added to the log')) setNote('')
                  }}
                >
                  Log
                </Button>
              </div>
              {t.log.length > 0 && (
                <ul className="divide-y divide-line rounded-md border border-line text-sm">
                  {t.log.slice(0, 10).map((e, i) => (
                    <li key={i} className="flex gap-3 px-3 py-2">
                      <span className="tabular shrink-0 text-xs text-faint">{e.date}</span>
                      <span className="min-w-0 flex-1">{e.note}</span>
                      <span className={cx('shrink-0 text-xs', e.impact === 'strengthens' ? 'text-up' : e.impact === 'weakens' ? 'text-down' : 'text-muted')}>
                        {IMPACT[e.impact]}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" icon="pencil" onClick={() => setEditing(true)}>
                Edit
              </Button>
              <Button size="sm" variant="ghost" icon="check" loading={busy} onClick={() => run(() => markThesisReviewed(t.id), 'Marked as reviewed')}>
                Reviewed, still holds
              </Button>
              {confirming ? (
                <>
                  <Button size="sm" variant="danger" icon="trash" onClick={remove}>
                    Delete thesis and log
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(false)}>
                    Keep it
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="ghost" icon="trash" onClick={() => setConfirming(true)}>
                  Delete
                </Button>
              )}
            </div>
            <p className="text-[12px] text-faint">Your own view, checked against market data. Not advice.</p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
