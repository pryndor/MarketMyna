import { useEffect, useState, type FormEvent } from 'react'
import { deleteApiKey, getApiKeys, getMe, putApiKey, type ApiKeys } from '../api/account'
import { errorMessage, serverTime } from '../lib/format'
import { useSession } from '../lib/session'
import { toast } from '../lib/toast'
import { Badge, Button, Card, CardBody, CardHeader, Field, Textarea } from './ui'

const PROVIDER_LABELS: Record<string, string> = {
  gemini: 'Google Gemini',
  groq: 'Groq',
  openrouter: 'OpenRouter',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  deepseek: 'DeepSeek',
  mistral: 'Mistral',
}

function date(iso: string | null | undefined): string {
  return iso ? serverTime(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
}

/** The one place to set up AI: paste a key (or several, for fallback). */
export default function AiKeysCard() {
  const setMe = useSession((s) => s.setMe)
  const [data, setData] = useState<ApiKeys | null>(null)
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getApiKeys()
      .then(setData)
      .catch((err) => toast.error(errorMessage(err)))
  }, [])

  async function after(next: ApiKeys) {
    setData(next)
    setMe(await getMe())
  }

  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const before = new Set(data?.keys.map((k) => k.id))
      const next = await putApiKey(key)
      await after(next)
      setKey('')
      const added = next.keys.filter((k) => !before.has(k.id))
      if (added.length === 1) {
        toast.success(`${PROVIDER_LABELS[added[0].provider] ?? added[0].provider} key detected and saved.`)
      } else if (added.length > 1) {
        toast.success(`${added.length} keys detected and saved.`)
      } else {
        toast.success('Already saved.')
      }
      for (const err of next.errors ?? []) toast.error(err)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: number) {
    try {
      await after(await deleteApiKey(id))
      toast.success('Key removed.')
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  return (
    <Card>
      <CardHeader
        title="AI keys"
        icon="cpu"
        description="Paste a key and the app works out the provider and picks a model, a free one where the key allows it. Stored encrypted; only the last 4 characters are ever shown."
      />
      <CardBody className="space-y-4">
        {data?.keys.length ? (
          <>
            {data.keys.length > 1 && (
              <p className="text-xs text-muted">Tried in this order: when a key fails or hits its limit, the next one answers.</p>
            )}
            <ol className="divide-y divide-line rounded-lg border border-line">
              {data.keys.map((k, i) => (
                <li key={k.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                  {data.keys.length > 1 && <span className="tabular w-4 text-xs text-faint">{i + 1}</span>}
                  <span className="font-medium">{PROVIDER_LABELS[k.provider] ?? k.provider}</span>
                  <span className="tabular text-muted">•••• {k.last4}</span>
                  {k.free === true && <Badge tone="up">Free</Badge>}
                  {k.free === false && <Badge>Paid</Badge>}
                  <span className="text-xs text-faint">added {date(k.added_at)}</span>
                  <Button size="sm" variant="ghost" icon="trash" className="ms-auto" onClick={() => remove(k.id)}>
                    Remove
                  </Button>
                  {(k.model || k.note) && (
                    <p className="w-full text-xs text-muted">
                      {k.model && <span className="font-mono">{k.model.split('/').slice(1).join('/')}</span>}
                      {k.model && k.note && ' · '}
                      {k.note}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p className="text-sm text-muted">
            No keys yet: AI features are off until you add one. (Running a local model instead? Set LLM_MODEL and
            OLLAMA_BASE_URL in .env, see .env.example.)
          </p>
        )}
        {/* Top-aligned like the profile form: the hint under the field would otherwise push the button below it. */}
        <form onSubmit={save} className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-start">
          <Field
            label="API key"
            hint="Anthropic, Google Gemini, Groq, Mistral or OpenRouter. Paste several at once (one per line) for automatic fallback."
          >
            <Textarea
              autoComplete="off"
              spellCheck={false}
              rows={key.includes('\n') ? 3 : 1}
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Paste key"
              className="min-h-9 resize-y py-2 font-mono text-xs [-webkit-text-security:disc]"
            />
          </Field>
          <Button
            type="submit"
            className="sm:mt-[calc(var(--text-xs--line-height)+0.375rem)]"
            loading={busy}
            disabled={key.trim().length < 8}
          >
            {busy ? 'Checking…' : 'Save key'}
          </Button>
        </form>
      </CardBody>
    </Card>
  )
}
