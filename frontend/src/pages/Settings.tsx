import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  isSecretKind,
  NOTIFICATION_CHANNELS,
  getNotificationSettings,
  isSecretValue,
  testNotificationSettings,
  updateNotificationSettings,
  type FieldSpec,
  type FieldValue,
  type TestNotificationsResult,
} from '../api/systemConfig'
import { toast } from '../lib/toast'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Field,
  Icon,
  Input,
  PageHeader,
  Skeleton,
  StatusDot,
  Switch,
  Textarea,
  SecretInput,
} from '../components/ui'
import { cx } from '../lib/cx'
import NotificationRouting from '../components/NotificationRouting'
import PushNotifications from '../components/PushNotifications'
import { errorMessage } from '../lib/format'
import AiKeysCard from '../components/AiKeysCard'
import DataSources from '../components/DataSources'
import UpdatesCard from '../components/UpdatesCard'

type Tab = 'ai' | 'notifications' | 'data'

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>('ai')
  return (
    <div>
      <PageHeader title="Settings" description="AI keys, where reports and alerts go, and optional data sources." />
      <div className="no-scrollbar -mx-4 mb-6 flex gap-1 overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0">
        {(
          [
            ['ai', 'AI keys', 'cpu'],
            ['notifications', 'Notifications', 'bell'],
            ['data', 'Data sources', 'candles'],
          ] as const
        ).map(([id, label, icon]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={cx(
              '-mb-px flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium',
              tab === id ? 'border-accent text-fg' : 'border-transparent text-muted hover:text-fg',
            )}
          >
            <Icon name={icon} /> {label}
          </button>
        ))}
      </div>
      {tab === 'ai' ? (
        <AiKeysCard />
      ) : tab === 'data' ? (
        <DataSources />
      ) : (
        <div className="space-y-6">
          <PushNotifications />
          <NotificationSettings />
          <NotificationRouting />
        </div>
      )}
      <div className="mt-8">
        <UpdatesCard />
      </div>
      <p className="mt-4 text-xs text-muted">
        MarketMyna is open source under the Apache License 2.0.{' '}
        <a
          className="underline hover:text-fg"
          href="https://github.com/pryndor/MarketMyna"
          target="_blank"
          rel="noreferrer"
        >
          Source code
        </a>
      </p>
    </div>
  )
}

/* ------------------------------------------------------ shared form state */

/** Holds the editable form for a set of fields and computes the minimal
 * PUT payload. Secrets never come back from the API (only {is_set}), so a
 * blank secret input means "keep what's saved"; clearing one is explicit. */
function useSettingsForm(specs: FieldSpec[]) {
  const [original, setOriginal] = useState<Record<string, string>>({})
  const [values, setValues] = useState<Record<string, string>>({})
  const [secretSet, setSecretSet] = useState<Record<string, boolean>>({})
  const [cleared, setCleared] = useState<Set<string>>(new Set())

  const hydrate = useCallback((flat: Record<string, FieldValue>) => {
    const next: Record<string, string> = {}
    const secrets: Record<string, boolean> = {}
    for (const spec of specs) {
      const v = flat[spec.attr]
      if (isSecretValue(v)) {
        secrets[spec.attr] = v.is_set
        next[spec.attr] = ''
      } else {
        next[spec.attr] = v == null ? '' : Array.isArray(v) ? v.join(', ') : String(v)
      }
    }
    setOriginal(next)
    setValues(next)
    setSecretSet(secrets)
    setCleared(new Set())
  }, [specs])

  const payload = useMemo(() => {
    const out: Record<string, unknown> = {}
    for (const spec of specs) {
      const raw = values[spec.attr] ?? ''
      if (isSecretKind(spec.kind)) {
        const asList = spec.kind === 'secret_list'
        if (cleared.has(spec.attr)) out[spec.attr] = asList ? [] : ''
        else if (raw !== '') out[spec.attr] = asList ? raw.split(',').map((x) => x.trim()).filter(Boolean) : raw
        continue
      }
      if (raw === (original[spec.attr] ?? '')) continue
      out[spec.attr] = coerce(spec, raw)
    }
    return out
  }, [specs, values, original, cleared])

  return {
    values,
    secretSet,
    cleared,
    payload,
    dirty: Object.keys(payload).length > 0,
    hydrate,
    set: (attr: string, v: string) => {
      setValues((p) => ({ ...p, [attr]: v }))
      setCleared((c) => {
        if (!c.has(attr)) return c
        const n = new Set(c)
        n.delete(attr)
        return n
      })
    },
    clearSecret: (attr: string) => {
      setValues((p) => ({ ...p, [attr]: '' }))
      setCleared((c) => new Set(c).add(attr))
    },
    reset: () => {
      setValues(original)
      setCleared(new Set())
    },
  }
}

function coerce(spec: FieldSpec, raw: string): unknown {
  const s = raw.trim()
  if (spec.kind === 'bool') return raw === 'true'
  if (s === '') return null
  if (spec.kind === 'int') return Number.isFinite(Number(s)) ? parseInt(s, 10) : null
  if (spec.kind === 'float') return Number.isFinite(Number(s)) ? parseFloat(s) : null
  if (spec.kind === 'list') return s.split(',').map((x) => x.trim()).filter(Boolean)
  return raw
}

/** Splits "Label (extra hint)" labels from the backend schema into a
 * short label plus a hint line, so fields read cleanly. */
function splitLabel(label: string): [string, string | undefined] {
  const m = label.match(/^(.*?)\s*\((.*)\)$/)
  return m ? [m[1], m[2]] : [label, undefined]
}

function SettingField({
  spec,
  form,
}: {
  spec: FieldSpec
  form: ReturnType<typeof useSettingsForm>
}) {
  const [label, hint] = splitLabel(spec.label)
  const value = form.values[spec.attr] ?? ''

  if (spec.kind === 'bool') {
    return <Switch checked={value === 'true'} onChange={(v) => form.set(spec.attr, String(v))} label={label} description={hint} />
  }

  if (isSecretKind(spec.kind)) {
    const isSet = form.secretSet[spec.attr] && !form.cleared.has(spec.attr)
    return (
      <Field
        label={
          <span className="flex items-center gap-2">
            {label}
            {form.cleared.has(spec.attr) ? (
              <Badge tone="warn">will clear</Badge>
            ) : isSet ? (
              <Badge tone="up">
                <Icon name="lock" className="h-3 w-3" /> saved
              </Badge>
            ) : null}
          </span>
        }
        hint={hint}
      >
        <div className="flex gap-2">
          <SecretInput
            value={value}
            onChange={(e) => form.set(spec.attr, e.target.value)}
            placeholder={isSet ? '•••••••• (leave blank to keep)' : 'Not set'}
          />
          {isSet && (
            <Button variant="ghost" size="md" onClick={() => form.clearSecret(spec.attr)} title="Remove saved secret on save">
              Clear
            </Button>
          )}
        </div>
      </Field>
    )
  }

  if (spec.kind === 'multiline') {
    return (
      <Field label={label} hint={hint}>
        <Textarea rows={3} value={value} onChange={(e) => form.set(spec.attr, e.target.value)} />
      </Field>
    )
  }

  return (
    <Field label={label} hint={hint}>
      <Input
        type={spec.kind === 'int' || spec.kind === 'float' ? 'number' : 'text'}
        step={spec.kind === 'float' ? 'any' : undefined}
        value={value}
        onChange={(e) => form.set(spec.attr, e.target.value)}
      />
    </Field>
  )
}

function SaveBar({
  dirty,
  saving,
  onSave,
  onReset,
  extra,
}: {
  dirty: boolean
  saving: boolean
  onSave: () => void
  onReset: () => void
  extra?: React.ReactNode
}) {
  return (
    <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
      <span className="flex items-center gap-2 text-xs text-muted">
        <StatusDot tone={dirty ? 'warn' : 'up'} />
        {dirty ? 'Unsaved changes' : 'Up to date'}
      </span>
      <div className="flex gap-2">
        {extra}
        <Button variant="ghost" size="sm" disabled={!dirty} onClick={onReset}>
          Reset
        </Button>
        <Button size="sm" loading={saving} disabled={!dirty} onClick={onSave}>
          Save
        </Button>
      </div>
    </footer>
  )
}

/* ---------------------------------------------------- notifications tab */

const ALL_NOTIFICATION_FIELDS = NOTIFICATION_CHANNELS.flatMap((c) => c.fields)

function flatten(data: Record<string, Record<string, FieldValue>>) {
  return Object.assign({}, ...Object.values(data)) as Record<string, FieldValue>
}

function NotificationSettings() {
  const form = useSettingsForm(ALL_NOTIFICATION_FIELDS)
  const { hydrate } = form
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState(NOTIFICATION_CHANNELS[0].name)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<TestNotificationsResult | null>(null)

  useEffect(() => {
    getNotificationSettings()
      .then((data) => {
        hydrate(flatten(data))
        setLoaded(true)
      })
      .catch((err) => setError(errorMessage(err)))
  }, [hydrate])

  /** A channel counts as configured once its primary (first) field has a
   * value - the backend's own configured_channels() is authoritative and
   * is what Send test reports. */
  function channelState(name: string): 'on' | 'off' | 'dirty' {
    const channel = NOTIFICATION_CHANNELS.find((c) => c.name === name)!
    if (channel.fields.some((f) => f.attr in form.payload)) return 'dirty'
    const primary = channel.fields[0]
    const on = primary.kind === 'password' ? form.secretSet[primary.attr] : (form.values[primary.attr] ?? '') !== ''
    return on ? 'on' : 'off'
  }

  async function save() {
    setSaving(true)
    try {
      form.hydrate(flatten(await updateNotificationSettings(form.payload)))
      toast.success('Notification settings saved')
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function test() {
    setTesting(true)
    setTestResult(null)
    try {
      const result = await testNotificationSettings(form.payload)
      setTestResult(result)
      if (!result.configured_channels.length) toast.info(result.message ?? 'No channel configured')
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setTesting(false)
    }
  }

  if (error) return <Alert title="Could not load notification settings">{error}</Alert>
  if (!loaded) return <Skeleton className="h-96 w-full" />

  const channel = NOTIFICATION_CHANNELS.find((c) => c.name === selected)!
  const activeCount = NOTIFICATION_CHANNELS.filter((c) => channelState(c.name) === 'on').length

  return (
    <div className="space-y-6">
      {testResult && testResult.configured_channels.length > 0 && (
        <Card>
          <CardHeader title="Test delivery" description="Sent with your current (unsaved included) values" />
          <div className="flex flex-wrap gap-2 p-5">
            {Object.entries(testResult.results).map(([name, ok]) => (
              <Badge key={name} tone={ok ? 'up' : 'down'}>
                <Icon name={ok ? 'check' : 'x'} className="h-3 w-3" /> {name}
              </Badge>
            ))}
          </div>
        </Card>
      )}

      <Card className="overflow-hidden">
        <div className="grid md:grid-cols-[220px_minmax(0,1fr)]">
          <nav className="border-line md:border-e">
            <div className="px-4 py-3 text-xs text-muted">{activeCount} of {NOTIFICATION_CHANNELS.length} channels active</div>
            <ul className="flex gap-1 overflow-x-auto px-2 pb-2 md:block md:space-y-0.5 md:overflow-visible">
              {NOTIFICATION_CHANNELS.map((c) => {
                const state = channelState(c.name)
                return (
                  <li key={c.name} className="shrink-0">
                    <button
                      type="button"
                      onClick={() => setSelected(c.name)}
                      className={cx(
                        'flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-start text-sm',
                        c.name === selected ? 'bg-raised text-fg' : 'text-muted hover:text-fg',
                      )}
                    >
                      {c.name}
                      <StatusDot tone={state === 'on' ? 'up' : state === 'dirty' ? 'warn' : 'neutral'} />
                    </button>
                  </li>
                )
              })}
            </ul>
          </nav>

          <div className="min-w-0">
            <CardHeader
              title={channel.name}
              description={
                channelState(channel.name) === 'on'
                  ? 'Active - receives scheduled and manual run results.'
                  : 'Not configured - fill the fields below to enable.'
              }
              icon="bell"
            />
            <CardBody className="grid gap-4 sm:grid-cols-2">
              {channel.fields.map((spec) => (
                <div key={spec.attr} className={spec.kind === 'multiline' || spec.kind === 'bool' ? 'sm:col-span-2' : undefined}>
                  <SettingField spec={spec} form={form} />
                </div>
              ))}
            </CardBody>
          </div>
        </div>
        <SaveBar
          dirty={form.dirty}
          saving={saving}
          onSave={save}
          onReset={form.reset}
          extra={
            <Button variant="secondary" size="sm" icon="send" loading={testing} onClick={test}>
              Send test
            </Button>
          }
        />
      </Card>
    </div>
  )
}
