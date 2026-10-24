import { useEffect, useState } from 'react'
import { getMdnaSummary, type MdnaSummary } from '../api/stocks'
import { errorMessage } from '../lib/format'
import { MiniMarkdown } from './FinancialStatements'
import { Button, Card, CardBody, CardHeader } from './ui'

/** On-demand AI summary of the MD&A in the latest 10-K / 10-Q (US only). */
export default function MdnaCard({ symbol }: { symbol: string }) {
  const [data, setData] = useState<MdnaSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setData(null)
    setError(null)
  }, [symbol])

  async function run() {
    setLoading(true)
    setError(null)
    try {
      setData(await getMdnaSummary(symbol))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card id="section-mdna" section="Management discussion">
      <CardHeader
        title="What management says"
        description={
          data
            ? `AI summary of MD&A in the ${data.form} for the period to ${data.period} (filed ${data.filed})`
            : "AI summary of the Management's Discussion & Analysis in the latest SEC 10-K / 10-Q"
        }
        actions={
          <Button variant={data ? 'ghost' : 'primary'} size="sm" icon="cpu" loading={loading} onClick={run}>
            {data ? 'Refresh' : loading ? 'Reading filing…' : 'Summarise filing'}
          </Button>
        }
      />
      <CardBody>
        {error && <p className="text-sm text-down">{error}</p>}
        {!data && !error && !loading && (
          <p className="text-sm text-muted">
            Reads what the company itself says about results, drivers, outlook and risks. Takes about 20-40 seconds.
          </p>
        )}
        {loading && !data && <p className="text-sm text-muted">Fetching the latest annual or quarterly filing and summarising…</p>}
        {data && (
          <div className="space-y-3">
            <div className="text-sm leading-relaxed">
              <MiniMarkdown text={data.summary} />
            </div>
            <a href={data.url} target="_blank" rel="noreferrer" className="text-xs text-accent-fg hover:underline">
              Read the full {data.form} on SEC.gov ↗
            </a>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
