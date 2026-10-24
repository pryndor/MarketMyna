import { useEffect, useState } from 'react'
import { apiClient } from '../api/client'
import { applyUpdate, checkUpdates, getUpdateStatus, saveUpdateSettings, type UpdateCheck } from '../api/updates'
import { toast } from '../lib/toast'
import { errorMessage, relativeTime } from '../lib/format'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Select, Spinner } from './ui'

const INSTALL_LABEL: Record<UpdateCheck['install'], string> = {
  source: 'Installed from source (git)',
  zip: 'Installed from a release zip',
  package: 'Installed with pipx / pip',
}

const INTERVALS = [
  { value: '5', label: 'Every 5 minutes' },
  { value: '60', label: 'Every hour' },
  { value: '120', label: 'Every 2 hours' },
  { value: '0', label: 'Off' },
]

type Phase = 'idle' | 'confirm' | 'installing' | 'restarting'

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

/** After Update now: wait for the app to go down and come back, then reload onto the new version. */
async function waitForRestart(): Promise<boolean> {
  await sleep(4000)
  for (let i = 0; i < 150; i++) {
    try {
      await apiClient.get('/health', { timeout: 3000 })
      return true
    } catch {
      await sleep(2000)
    }
  }
  return false
}

/** Settings: this copy against github.com/pryndor/MarketMyna - its releases and,
 * for a git checkout, the newest code on main. The server also checks on its own
 * (every 5 minutes by default); Update now installs it and restarts the app. */
export default function UpdatesCard() {
  const [result, setResult] = useState<UpdateCheck | null>(null)
  const [interval, setIntervalMinutes] = useState<string>('5')
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [phase, setPhase] = useState<Phase>('idle')
  const [log, setLog] = useState<string[]>([])

  // Show what the background check found last, without calling GitHub.
  useEffect(() => {
    getUpdateStatus()
      .then((s) => {
        if (s.checked_at) setResult(s)
        if (s.settings) setIntervalMinutes(String(s.settings.interval_minutes))
      })
      .catch(() => {})
  }, [])

  async function check() {
    setChecking(true)
    setError(null)
    try {
      const data = await checkUpdates(true)
      setResult(data)
      if (data.settings) setIntervalMinutes(String(data.settings.interval_minutes))
      if (data.error) return
      if (data.update_available) toast.info(data.release_available ? `MarketMyna ${data.latest} is available` : 'New code is on GitHub')
      else toast.success("You're on the latest version")
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setChecking(false)
    }
  }

  async function changeInterval(value: string) {
    const previous = interval
    setIntervalMinutes(value)
    try {
      await saveUpdateSettings({ interval_minutes: Number(value) })
      toast.success(value === '0' ? 'Automatic checks off' : 'Saved')
    } catch (err) {
      setIntervalMinutes(previous)
      toast.error(errorMessage(err))
    }
  }

  async function update() {
    setPhase('installing')
    setError(null)
    setLog([])
    try {
      const res = await applyUpdate()
      setLog(res.log)
      if (!res.restarting) {
        setPhase('idle')
        toast.success('Already up to date')
        return
      }
      setPhase('restarting')
      if (await waitForRestart()) {
        window.location.reload()
      } else {
        setPhase('idle')
        setError('MarketMyna did not come back after the update. Check the terminal it runs in, then start it again.')
      }
    } catch (err) {
      setPhase('idle')
      setError(errorMessage(err))
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast.success('Copied')
    } catch {
      toast.error('Could not copy - select the text instead')
    }
  }

  const code = result?.code
  const busy = phase === 'installing' || phase === 'restarting'
  return (
    <Card>
      <CardHeader
        title="Updates"
        description={
          result
            ? `Version ${result.current} · ${INSTALL_LABEL[result.install]}${code ? ` · commit ${code.local_sha}` : ''}`
            : 'Checks github.com/pryndor/MarketMyna for a new release or newer code.'
        }
        actions={
          <Button variant="secondary" size="sm" icon="refresh" loading={checking} disabled={busy} onClick={check}>
            Check for updates
          </Button>
        }
      />
      <CardBody className="space-y-4">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <label htmlFor="update-interval" className="text-sm text-muted">
            Check GitHub automatically
          </label>
          <Select
            id="update-interval"
            options={INTERVALS}
            value={interval}
            onChange={(e) => void changeInterval(e.target.value)}
            className="w-auto"
          />
          <span className="text-xs text-faint">The app checks while it runs; a new version also shows in the sidebar.</span>
        </div>

        {error && (
          <Alert title="Update problem">
            <span className="whitespace-pre-wrap">{error}</span>
          </Alert>
        )}
        {result?.error && <Alert title="Could not check for updates">{result.error}</Alert>}

        {result && !result.error && (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge tone={result.update_available ? 'accent' : 'up'}>{result.update_available ? 'Update available' : 'Up to date'}</Badge>
              {result.checked_at && (
                <span className="text-xs text-faint">last checked {relativeTime(new Date(result.checked_at * 1000).toISOString())}</span>
              )}
            </div>

            <dl className="divide-y divide-line rounded-lg border border-line text-sm">
              <div className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
                <dt className="text-muted">Latest release</dt>
                <dd className="flex flex-wrap items-baseline gap-2">
                  {result.latest ? (
                    <>
                      <span className={result.release_available ? 'font-semibold text-accent-fg' : ''}>{result.latest}</span>
                      <span className="text-xs text-faint">
                        {result.release_available ? `newer than your ${result.current}` : `you have ${result.current}`}
                      </span>
                    </>
                  ) : (
                    <span className="text-faint">none published yet</span>
                  )}
                  <a href={result.release?.url ?? result.releases_url} target="_blank" rel="noreferrer" className="text-xs font-medium text-accent hover:underline">
                    {result.release_available ? "What's new" : 'Releases'} ↗
                  </a>
                </dd>
              </div>
              {code && (
                <div className="flex flex-wrap items-baseline justify-between gap-2 px-3 py-2">
                  <dt className="text-muted">Latest code on main</dt>
                  <dd className="flex min-w-0 flex-wrap items-baseline gap-2">
                    <span className="font-mono text-xs">{code.remote_sha}</span>
                    <span className="text-xs text-faint">
                      {code.update_available
                        ? `newer than your ${code.local_sha}${code.remote_date ? ` · ${relativeTime(code.remote_date)}` : ''}`
                        : code.remote_sha === code.local_sha
                          ? 'same as yours'
                          : `yours (${code.local_sha}) is newer`}
                    </span>
                    {code.url && (
                      <a href={code.url} target="_blank" rel="noreferrer" className="text-xs font-medium text-accent hover:underline">
                        View ↗
                      </a>
                    )}
                  </dd>
                </div>
              )}
              {code?.update_available && code.message && <div className="px-3 py-2 text-xs text-muted">“{code.message}”</div>}
            </dl>

            {result.update_available && result.can_apply && (
              <div className="rounded-lg border border-accent/40 bg-accent-soft/40 p-4">
                {phase === 'idle' && (
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-sm">Install the update and restart MarketMyna. Your data, keys and settings are kept.</p>
                    <Button icon="refresh" onClick={() => setPhase('confirm')}>
                      Update now
                    </Button>
                  </div>
                )}
                {phase === 'confirm' && (
                  <div className="space-y-3">
                    <p className="text-sm">
                      {result.install === 'source'
                        ? 'MarketMyna moves this copy to the latest code from GitHub (your current commit is kept on a backup branch), installs any new requirements, rebuilds the pages and restarts. It stops if you have edited its files.'
                        : 'MarketMyna upgrades its package from PyPI and restarts.'}{' '}
                      The app is offline for a minute or two while it restarts.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button icon="refresh" onClick={() => void update()}>
                        Yes, update and restart
                      </Button>
                      <Button variant="ghost" onClick={() => setPhase('idle')}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}
                {busy && (
                  <div className="flex items-center gap-2 text-sm">
                    <Spinner className="h-4 w-4 text-accent-fg" />
                    {phase === 'installing'
                      ? 'Installing the update…'
                      : 'Restarting MarketMyna - this page reloads by itself when it is back (rebuilding the pages can take a minute).'}
                  </div>
                )}
              </div>
            )}

            {result.update_available && !result.can_apply && (
              <div className="space-y-2">
                <p className="text-xs text-muted">To update, stop MarketMyna and run (your data is kept):</p>
                {result.commands.map((cmd) => (
                  <div key={cmd} className="flex items-start gap-2">
                    <code className="min-w-0 flex-1 break-all rounded-md bg-canvas px-3 py-2 font-mono text-xs">{cmd}</code>
                    <Button variant="ghost" size="sm" onClick={() => copy(cmd)} title="Copy">
                      Copy
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {log.length > 0 && (
          <details className="text-xs" open={phase === 'idle' && !!error}>
            <summary className="cursor-pointer text-muted">Update log</summary>
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-canvas p-3 font-mono text-[11px]">{log.join('\n')}</pre>
          </details>
        )}
      </CardBody>
    </Card>
  )
}
