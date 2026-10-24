import { useEffect, useState, type ReactNode } from 'react'
import { searchListings } from '../api/listings'
import SymbolSearch from './SymbolSearch'
import type { ReportOptions, SmartFile } from '../api/scheduler'
import type { ReportDraft } from '../pages/Scheduler'
import { cx } from '../lib/cx'
import { shows, useSection } from '../lib/section'
import { Alert, Button, Card, CardBody, CardHeader, Field, Icon, Input, Select, Skeleton, Switch } from './ui'

const CHANNEL_LABELS: Record<string, string> = {
  telegram: 'Telegram', discord: 'Discord', slack: 'Slack', email: 'Email', dingtalk: 'DingTalk', feishu: 'Feishu',
  wechat: 'WeChat', pushover: 'Pushover', ntfy: 'ntfy', gotify: 'Gotify', pushplus: 'PushPlus',
  serverchan3: 'ServerChan3', astrbot: 'AstrBot', webhook: 'Webhook', webpush: 'Browser push',
  whatsapp: 'WhatsApp', twilio: 'Twilio SMS', teams: 'Teams', googlechat: 'Google Chat', matrix: 'Matrix',
  signal: 'Signal', bark: 'Bark', pushbullet: 'Pushbullet', apprise: 'Apprise',
}

/** Channels that can carry Smart messaging's report file (server: SMART_FILE_CHANNELS). */
const FILE_CHANNELS = [
  { id: 'email', label: 'Email' },
  { id: 'telegram', label: 'Telegram' },
]

/** Built once per report (src/services/report.py REPORT_WIDE), never per stock. */
const REPORT_WIDE = new Set(['market', 'calls', 'portfolio', 'alerts', 'hot_trade', 'hot_invest', 'funds'])

/** What the scheduled report contains and which language each channel
 * gets. Lives on the Scheduler page and saves with the schedule. */
export default function ReportSettings({
  draft,
  options,
  onChange,
  footer,
}: {
  draft: ReportDraft
  options: ReportOptions | null
  onChange: (patch: Partial<ReportDraft>) => void
  footer: ReactNode
}) {
  const section = useSection()
  const [openStock, setOpenStock] = useState<string | null>(null)
  const [fundSearch, setFundSearch] = useState('')
  const [fundNames, setFundNames] = useState<Record<string, string>>({})

  // Saved funds come back as bare scheme codes; look their names up once.
  const missingNames = draft.mfCodes.filter((c) => !(c in fundNames)).join(',')
  useEffect(() => {
    if (!missingNames) return
    let cancelled = false
    for (const code of missingNames.split(',')) {
      searchListings(code, 'india', 'mf', 1)
        .then((rows) => {
          const hit = rows.find((r) => r.symbol === code)
          if (!cancelled) setFundNames((n) => ({ ...n, [code]: hit?.name ?? `Scheme ${code}` }))
        })
        .catch(() => {})
    }
    return () => {
      cancelled = true
    }
  }, [missingNames])

  if (!options) {
    return (
      <Card>
        <CardHeader title="Report content & delivery" icon="bell" />
        <CardBody>
          <Skeleton className="h-40 w-full" />
        </CardBody>
      </Card>
    )
  }

  const languageOptions = options.languages.map((l) => ({
    value: l.code,
    label: `${l.native}${l.native !== l.english ? ` · ${l.english}` : ''}${l.builtin ? '' : ' (AI)'}`,
  }))
  const selectedLang = options.languages.find((l) => l.code === draft.reportLanguage)
  // Each area sees its own sections; the other area's choices stay saved as they are.
  const visible = options.sections.filter((s) => shows(section, s.area ?? undefined))
  const visibleIds = new Set(visible.map((s) => s.id))
  // Saved sections that belong to the other area. Ids missing from the catalogue (an
  // old saved section) aren't in the report, so skip them.
  const hiddenOn = draft.reportSections.filter((id) => !visibleIds.has(id) && options.sections.some((s) => s.id === id))
  const showFunds = visibleIds.has('funds')
  // Built once per report, not per stock, so they can't be customised per stock.
  const perStock = visible.filter((s) => !REPORT_WIDE.has(s.id))

  // Keep catalogue order so the report reads the same every day.
  function ordered(ids: string[]): string[] {
    return options!.sections.map((s) => s.id).filter((s) => ids.includes(s))
  }

  function toggleSection(list: string[], id: string): string[] {
    return ordered(list.includes(id) ? list.filter((s) => s !== id) : [...list, id])
  }

  function setStock(symbol: string, sections: string[] | null) {
    const next = { ...draft.stockSections }
    if (sections === null) delete next[symbol]
    else next[symbol] = sections
    onChange({ stockSections: next })
  }


  return (
    <Card>
      <CardHeader
        title="Report content & delivery"
        description="Choose what each report contains and the language every channel receives."
        icon="bell"
      />
      <CardBody className="space-y-7">
        {!options.llm_configured && (
          <Alert tone="accent" title="No AI model configured">
            Reports still arrive with prices, technical, risk, fundamentals and news, and labels in the built-in languages.
            The AI view (a bullish / neutral / bearish outlook with its reasoning), AI-only languages and translation of free text such as headlines need
            an AI model under Settings.
          </Alert>
        )}

        {/* ---------------------------------------------------- language */}
        <section className="grid gap-6 md:grid-cols-2">
          <Field
            label="Report language"
            hint={
              selectedLang && !selectedLang.builtin
                ? 'Translated entirely by your AI model.'
                : 'Labels are built in; AI commentary and headlines are translated when an AI model is set.'
            }
          >
            <Select
              options={languageOptions}
              value={draft.reportLanguage}
              onChange={(e) => onChange({ reportLanguage: e.target.value })}
            />
          </Field>

          <div>
            <span className="mb-1.5 block text-xs font-medium text-muted">Language per channel</span>
            {options.channels.length === 0 ? (
              <p className="rounded-lg border border-dashed border-line px-3 py-2.5 text-xs text-muted">
                No notification channel configured yet. Add Telegram, email and others under{' '}
                <a href="/settings" className="text-accent-fg hover:underline">
                  Settings → Notifications
                </a>
                .
              </p>
            ) : (
              <ul className="space-y-2">
                {options.channels.map((ch) => (
                  <li key={ch} className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-3">
                    <span className="text-sm">{CHANNEL_LABELS[ch] ?? ch}</span>
                    <Select
                      options={[{ value: '', label: 'Same as report language' }, ...languageOptions]}
                      value={draft.channelLanguages[ch] ?? ''}
                      onChange={(e) => {
                        const next = { ...draft.channelLanguages }
                        if (e.target.value) next[ch] = e.target.value
                        else delete next[ch]
                        onChange({ channelLanguages: next })
                      }}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

        {/* ---------------------------------------------------- smart messaging */}
        <section
          className={cx(
            'rounded-lg border px-4 py-3.5',
            draft.smartEnabled ? 'border-accent/60 bg-accent-soft/40' : 'border-line',
          )}
        >
          <Switch
            checked={draft.smartEnabled}
            onChange={(smartEnabled) => onChange({ smartEnabled })}
            label="Smart messaging"
            description={
              <>
                For long watchlists: instead of a block per stock, the message carries only today's top{' '}
                {draft.smartTopN} stocks in one or two lines each. Every stock (normal range, P/E, 1-week range and a
                bullish / neutral / bearish reading of its indicators) goes into a full report, sent by email and opened
                by link. No buy or sell calls, targets or stops.
                {draft.symbols.length >= 30 && !draft.smartEnabled && (
                  <b className="text-fg"> Recommended: each run covers {draft.symbols.length} stocks.</b>
                )}
              </>
            }
          />
          {draft.smartEnabled && (
            <div className="mt-4 space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Stocks in the message" hint="Ranked by today's move, levels hit, RSI extremes and volume.">
                  <Select
                    options={[3, 5, 10].map((n) => ({ value: String(n), label: `Top ${n}` }))}
                    value={String(draft.smartTopN)}
                    onChange={(e) => onChange({ smartTopN: Number(e.target.value) })}
                  />
                </Field>
                <Field
                  label="AI review"
                  hint={
                    options.llm_configured
                      ? 'Only the most notable stocks get the AI pipeline, to keep AI cost low.'
                      : 'Needs an AI model (Settings). Without one, the bullish / neutral / bearish reading comes from the computed rules.'
                  }
                >
                  <Select
                    options={[
                      { value: '0', label: 'None (computed only)' },
                      ...[5, 10, 20].map((n) => ({ value: String(n), label: `Top ${n} stocks` })),
                    ]}
                    value={String(draft.smartAiTop)}
                    onChange={(e) => onChange({ smartAiTop: Number(e.target.value) })}
                  />
                </Field>
              </div>
              <div className="grid gap-4 sm:grid-cols-[200px_minmax(0,1fr)]">
                <Field
                  label="Report file"
                  hint="The key figures for every stock: market, calls, your portfolio, valuation vs sector, the AI summary, ranges and risk. News and alerts stay in the message."
                >
                  <Select
                    options={[
                      { value: 'pdf', label: 'PDF (to read)' },
                      { value: 'xlsx', label: 'Excel (to sort and filter)' },
                      { value: 'none', label: 'No file' },
                    ]}
                    value={draft.smartFile}
                    onChange={(e) => onChange({ smartFile: e.target.value as SmartFile })}
                  />
                </Field>
                {draft.smartFile !== 'none' && (
                  <div>
                    <span className="mb-1.5 block text-xs font-medium text-muted">Send the file to</span>
                    <div className="flex flex-wrap gap-4">
                      {FILE_CHANNELS.map((c) => (
                        <label key={c.id} className="flex cursor-pointer items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={draft.smartFileChannels.includes(c.id)}
                            onChange={() =>
                              onChange({
                                smartFileChannels: draft.smartFileChannels.includes(c.id)
                                  ? draft.smartFileChannels.filter((x) => x !== c.id)
                                  : [...draft.smartFileChannels, c.id],
                              })
                            }
                            className="h-4 w-4 accent-[var(--color-accent)]"
                          />
                          {c.label}
                        </label>
                      ))}
                    </div>
                    <span className="mt-1.5 block text-xs text-muted">
                      {draft.smartFileChannels.length === 0
                        ? 'Pick at least one, or the file is not sent.'
                        : 'Email gets it as an attachment, Telegram as a document after the short message. Set the channels up under Settings → Notifications.'}
                    </span>
                  </div>
                )}
              </div>
              <label className="flex cursor-pointer items-start gap-3">
                <input
                  type="checkbox"
                  checked={draft.smartEmailFull}
                  onChange={(e) => onChange({ smartEmailFull: e.target.checked })}
                  className="mt-0.5 h-4 w-4 accent-[var(--color-accent)]"
                />
                <span>
                  <span className="block text-sm font-medium">Email the full table</span>
                  <span className="block text-xs text-muted">
                    The email channel gets the short brief plus the full table of every stock.
                    {!options.channels.includes('email') && ' Email is not configured yet (Settings → Notifications).'}
                  </span>
                </span>
              </label>
              <Field
                label="Public address for report links (optional)"
                hint={
                  draft.reportBaseUrl.trim() && !/^https?:\/\/\S+$/.test(draft.reportBaseUrl.trim()) ? (
                    <span className="text-down">Start with http:// or https://</span>
                  ) : (
                    'Where your phone can open MarketMyna, e.g. a Tailscale or domain address. Messages then end with a link to the full report. Leave empty to rely on email and the Scheduler page.'
                  )
                }
              >
                <Input
                  value={draft.reportBaseUrl}
                  onChange={(e) => onChange({ reportBaseUrl: e.target.value })}
                  placeholder={typeof window !== 'undefined' ? window.location.origin : 'https://marketmyna.example.ts.net'}
                />
              </Field>
            </div>
          )}
        </section>

        {/* ---------------------------------------------------- sections */}
        <section className={cx(draft.smartEnabled && 'opacity-60')}>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <span className="text-xs font-medium text-muted">Sections in every report</span>
            <div className="flex gap-3 text-xs">
              <button
                type="button"
                className="text-muted hover:text-fg"
                onClick={() => onChange({ reportSections: ordered([...hiddenOn, ...visible.map((s) => s.id)]) })}
              >
                Select all
              </button>
              <button
                type="button"
                className="text-muted hover:text-fg"
                onClick={() => onChange({ reportSections: ordered([...hiddenOn, ...visible.filter((s) => s.default).map((s) => s.id)]) })}
              >
                Defaults
              </button>
            </div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((s) => {
              const on = draft.reportSections.includes(s.id)
              return (
                <label
                  key={s.id}
                  className={cx(
                    'flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors',
                    'cursor-pointer',
                    on ? 'border-accent/60 bg-accent-soft' : 'border-line hover:border-line-strong',
                  )}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => onChange({ reportSections: toggleSection(draft.reportSections, s.id) })}
                    className="mt-0.5 h-4 w-4 accent-[var(--color-accent)]"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 text-sm font-medium">
                      {s.label}
                    </span>
                    <span className="block text-xs text-muted">
                      {s.description}
                    </span>
                  </span>
                </label>
              )
            })}
          </div>
          {draft.smartEnabled && (
            <p className="mt-2 text-xs text-muted">
              Smart messaging is on: these sections and the per-stock choices below are used when it is turned off. The
              report file always carries the same key figures.
            </p>
          )}
          {draft.reportSections.length === 0 && (
            <p className="mt-2 text-xs text-warn">No sections selected: reports will only list each stock's name.</p>
          )}
          {hiddenOn.length > 0 && section && (
            <p className="mt-2 text-xs text-faint">
              Also in your report from the {section === 'trader' ? 'Investor' : 'Trader'} area:{' '}
              {hiddenOn.map((id) => options.sections.find((s) => s.id === id)?.label ?? id).join(', ')}.{' '}
              <button
                type="button"
                className="text-accent-fg hover:underline"
                onClick={() => onChange({ reportSections: draft.reportSections.filter((id) => visibleIds.has(id)) })}
              >
                Remove them
              </button>
            </p>
          )}
        </section>


        {/* ---------------------------------------------------- funds */}
        {showFunds && (
        <section className={cx(!draft.reportSections.includes('funds') && 'opacity-60')}>
          <span className="mb-1 block text-xs font-medium text-muted">Mutual funds to track</span>
          <p className="mb-3 text-xs text-muted">NAV, day change and 1-month / 1-year returns for each fund, in every report.</p>
          <SymbolSearch
            value={fundSearch}
            onChange={setFundSearch}
            market="india"
            type="mf"
            placeholder="Search a fund, e.g. Parag Parikh Flexi Cap Direct Growth"
            onSelect={(row) => {
              if (!draft.mfCodes.includes(row.symbol)) onChange({ mfCodes: [...draft.mfCodes, row.symbol] })
              setFundNames((n) => ({ ...n, [row.symbol]: row.name }))
              setFundSearch('')
            }}
          />
          {draft.mfCodes.length > 0 && (
            <ul className="mt-3 divide-y divide-line rounded-lg border border-line">
              {draft.mfCodes.map((code) => (
                <li key={code} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className="font-mono text-xs text-muted">{code}</span>
                  <span className="min-w-0 flex-1 truncate">{fundNames[code] ?? 'Scheme ' + code}</span>
                  <button
                    type="button"
                    onClick={() => onChange({ mfCodes: draft.mfCodes.filter((c) => c !== code) })}
                    className="rounded-md p-1 text-faint hover:bg-down-soft hover:text-down"
                    aria-label={`Remove ${code}`}
                  >
                    <Icon name="x" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
        )}

        {/* ---------------------------------------------------- per stock */}
        <section>
          <span className="mb-1 block text-xs font-medium text-muted">Per-stock sections</span>
          <p className="mb-3 text-xs text-muted">
            Give a stock its own sections, e.g. {section === 'trader' ? 'trade levels and indicators for active trades, news for event plays' : 'news and fundamentals for long-term holdings, valuation for ones you may add to'}.
            Report-wide sections (market overview, movers and AI outlook, portfolio, alerts, hot stocks) always follow the report settings above.
          </p>
          {draft.symbols.length === 0 ? (
            <p className="text-xs text-faint">Choose what to run above first.</p>
          ) : (
            <ul className="divide-y divide-line rounded-lg border border-line">
              {draft.symbols.map((sym) => {
                const own = draft.stockSections[sym]
                const open = openStock === sym
                return (
                  <li key={sym}>
                    <div className="flex items-center gap-3 px-3 py-2">
                      <span className="font-mono text-sm font-medium">{sym}</span>
                      <span className="min-w-0 flex-1 truncate text-xs text-muted">
                        {own
                          ? own.length
                            ? own.map((id) => options.sections.find((s) => s.id === id)?.label ?? id).join(', ')
                            : 'Name only'
                          : 'Uses report sections'}
                      </span>
                      {own && (
                        <button type="button" onClick={() => setStock(sym, null)} className="text-xs text-muted hover:text-fg">
                          Reset
                        </button>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          if (!own) setStock(sym, draft.reportSections.filter((id) => !REPORT_WIDE.has(id)))
                          setOpenStock(open ? null : sym)
                        }}
                      >
                        <Icon name="chevron" className={cx('h-3.5 w-3.5 transition-transform', open && 'rotate-90')} />
                        Customize
                      </Button>
                    </div>
                    {open && own && (
                      <div className="flex flex-wrap gap-1.5 border-t border-line bg-canvas/40 px-3 py-3">
                        {perStock.map((s) => {
                          const on = own.includes(s.id)
                          return (
                            <button
                              key={s.id}
                              type="button"
                              aria-pressed={on}
                              onClick={() => setStock(sym, toggleSection(own, s.id))}
                              className={cx(
                                'rounded-full border px-3 py-1 text-xs font-medium',
                                on ? 'border-accent bg-accent-soft text-fg' : 'border-line text-muted hover:text-fg',
                              )}
                            >
                              {s.label}
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </section>

      </CardBody>
      {footer}
    </Card>
  )
}
