import { Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getCommodities, getIndiaRates, type Commodity, type IndiaRates } from '../api/macro'
import { num, pct, trendClass } from '../lib/format'
import { DAILY_EVERY, liveEvery, useInsight } from '../lib/insight'
import InsightLive from './InsightLive'
import InsightLoader from './InsightLoader'


const inr = (v: number | null | undefined) =>
  v == null ? '—' : v.toLocaleString('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

/** RBI policy and money-market rates, the India yield curve and IBJA bullion prices. */
export default function IndiaRatesCard() {
  // RBI rates and IBJA prices change once a day; international gold / silver
  // in rupees follow the live futures price.
  const { data, error, at } = useInsight((signal) => getIndiaRates(signal), [], DAILY_EVERY)
  const failed = error != null
  const live = useInsight((signal) => getCommodities(signal), [], liveEvery(60_000))
  const intl: Commodity[] = live.data?.items ?? []

  return (
    <div>
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">India rates &amp; bullion</h2>
          <p className="text-xs text-muted">RBI policy rates, the government bond curve, and IBJA gold / silver prices</p>
          {live.data?.live?.live ? (
            <InsightLive live={live.data.live} at={live.at} />
          ) : (
            <InsightLive at={at} daily="Rates and IBJA prices update once a day" />
          )}
        </div>
      </div>
      <div className="space-y-6 px-5 pb-4">
        {failed && <p className="text-sm text-down">India rates are unavailable right now.</p>}
        {!data && !failed && <InsightLoader className="min-h-56" steps={['Reading RBI policy rates…', 'Building the government bond curve…', 'Fetching IBJA gold and silver prices…']} />}
        {data && (
          <>
            <Rbi rbi={data.rbi} />
            <Bullion ibja={data.ibja} intl={intl} />
          </>
        )}
      </div>
    </div>
  )
}

function Stale({ error }: { error?: string }) {
  return error ? <p className="rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">{error}</p> : null
}

function Rbi({ rbi }: { rbi: IndiaRates['rbi'] }) {
  if (!rbi.policy) return <Stale error={rbi.error} />
  const usd = rbi.fx?.find((f) => f.pair === 'USD/INR')
  return (
    <div className="space-y-4">
      <Stale error={rbi.stale ? rbi.error : undefined} />
      <div>
        <div className="mb-2 text-xs font-medium text-muted">RBI policy</div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 xl:grid-cols-7">
          {rbi.policy.map((p) => (
            <div key={p.key} className="rounded-lg bg-canvas px-3 py-2" title={p.note}>
              <div className="truncate text-xs text-muted">{p.label}</div>
              <div className="tabular text-lg font-semibold">{p.value == null ? '—' : `${num(p.value)}%`}</div>
            </div>
          ))}
          {rbi.call_rate && (
            <div className="rounded-lg bg-canvas px-3 py-2" title="Overnight interbank borrowing; sits inside the SDF-MSF corridor">
              <div className="truncate text-xs text-muted">Call money</div>
              <div className="tabular whitespace-nowrap text-lg font-semibold xl:text-base xl:leading-7">
                {num(rbi.call_rate.low)}–{num(rbi.call_rate.high)}%
              </div>
            </div>
          )}
        </div>
      </div>

      {rbi.curve && rbi.curve.length > 2 && (
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-xs font-medium text-muted">
              India government yield curve{rbi.gsec_as_of ? ` · ${rbi.gsec_as_of}` : ''}
            </div>
            {(() => {
              const short = rbi.curve[0]
              const ten = rbi.curve.reduce((a, b) => (Math.abs(b.years - 10) < Math.abs(a.years - 10) ? b : a))
              const spread = ten.yield - short.yield
              return (
                <span className="text-xs text-muted">
                  ~10Y − {short.label}: <span className="tabular text-fg">{spread > 0 ? '+' : ''}{num(spread)} pts</span>
                </span>
              )
            })()}
          </div>
          <div className="h-52 rounded-lg bg-canvas p-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rbi.curve} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="var(--color-line)" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} interval={0} />
                <YAxis width={40} domain={['auto', 'auto']} tickFormatter={(v: number) => `${num(v, 1)}%`}
                  tick={{ fill: 'var(--color-faint)', fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{ background: 'var(--color-raised)', border: '1px solid var(--color-line-strong)', borderRadius: 8, fontSize: 12 }}
                  formatter={(v) => [`${num(Number(v), 2)}%`, 'Yield']}
                  labelFormatter={(l) => (String(l).endsWith('D') ? `${String(l).slice(0, -1)}-day T-bill` : `G-sec maturing ${l}`)}
                />
                <Line dataKey="yield" stroke="var(--color-accent)" strokeWidth={2} dot={{ r: 2.5 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="mt-1.5 text-[12px] text-faint">
            T-bills: cut-off at the last auction. Bonds: RBI's benchmark G-secs, labelled by maturity year. A steeper curve means
            the market expects higher rates or inflation later.
          </p>
        </div>
      )}

      {(usd || rbi.lending?.length) && (
        <div className="grid gap-x-8 gap-y-1 text-xs sm:grid-cols-2">
          {rbi.fx?.slice(0, 4).map((f) => (
            <div key={f.pair} className="flex justify-between border-b border-line py-1">
              <span className="text-muted">{f.per > 1 ? `${f.per} ` : ''}{f.pair} (FBIL)</span>
              <span className="tabular">₹{num(f.value, 2)}</span>
            </div>
          ))}
          {rbi.lending?.map((l) => (
            <div key={l.label} className="flex justify-between border-b border-line py-1">
              <span className="text-muted">{l.label}</span>
              <span className="tabular">{l.value}</span>
            </div>
          ))}
        </div>
      )}
      <p className="text-[12px] text-faint">Source: Reserve Bank of India (rbi.org.in){rbi.fx_as_of ? `; FX as at ${rbi.fx_as_of}` : ''}.</p>
    </div>
  )
}

function Bullion({ ibja, intl }: { ibja: IndiaRates['ibja']; intl: Commodity[] }) {
  if (!ibja.items) return <Stale error={ibja.error} />
  const intlFor: Record<string, Commodity | undefined> = {
    gold_999: intl.find((c) => c.key === 'GC=F:INR'),
    silver_999: intl.find((c) => c.key === 'SI=F:INR'),
  }
  const show = ibja.items.filter((i) => ['gold_999', 'gold_916', 'silver_999'].includes(i.key))
  return (
    <div className="space-y-3">
      <Stale error={ibja.stale ? ibja.error : undefined} />
      <div className="text-xs font-medium text-muted">
        Bullion in India (IBJA){ibja.as_of ? ` · ${ibja.as_of}` : ''}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {show.map((i) => {
          const hist = ibja.history?.[i.key] ?? []
          const ref = intlFor[i.key]
          const premium = ref ? (i.latest / ref.price - 1) * 100 : null
          return (
            <div key={i.key} className="rounded-lg bg-canvas px-3 py-2">
              <div className="flex justify-between gap-2 text-xs text-muted">
                <span className="truncate">{i.label}</span>
                <span className="shrink-0 text-faint">{i.unit} · {i.session}</span>
              </div>
              <div className="flex items-end justify-between gap-2">
                <div className="min-w-0">
                  <div className="tabular text-lg font-semibold">{inr(i.latest)}</div>
                  {i.change_pct != null && (
                    <div className="tabular whitespace-nowrap text-[11px] text-faint">
                      vs yesterday <span className={trendClass(i.change_pct)}>{pct(i.change_pct, 2)}</span>
                    </div>
                  )}
                  {premium != null && (
                    <div className="tabular whitespace-nowrap text-[11px] text-faint" title={`International price in rupees: ${inr(ref!.price)}`}>
                      {premium >= 0 ? '+' : ''}{num(premium, 1)}% over international
                    </div>
                  )}
                </div>
                {hist.length > 5 && (
                  <div className="h-10 w-16 shrink-0 sm:w-20">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={hist} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
                        <YAxis hide domain={['auto', 'auto']} />
                        <Area type="monotone" dataKey="value" stroke="var(--color-accent)" strokeWidth={1.5} fill="var(--color-accent)" fillOpacity={0.12} isAnimationActive={false} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <p className="text-[12px] text-faint">
        Source: India Bullion and Jewellers Association (ibjarates.com), before 3% GST and making charges. The premium over
        the international price is mostly import duty and local demand. MCX futures are not shown: MCX blocks automated access.
      </p>
    </div>
  )
}
