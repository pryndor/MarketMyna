import { useCallback, useEffect, useState } from 'react'
import {
  getIntegrations,
  testIntegration,
  updateIntegrations,
  type IntegrationField,
  type Integrations,
} from '../api/account'
import { errorMessage } from '../lib/format'
import { toast } from '../lib/toast'
import { Alert, Button, Card, CardBody, CardHeader, Field, Input, SecretInput, Skeleton, Switch } from './ui'

const ICONS = { finnhub: 'globe', market_data: 'candles', social: 'chat' } as const

/** Optional data-source keys: live US prices, backup price sources, Reddit. */
export default function DataSources() {
  const [data, setData] = useState<Integrations | null>(null)

  const load = useCallback(() => {
    getIntegrations()
      .then(setData)
      .catch((err) => toast.error(errorMessage(err)))
  }, [])
  useEffect(load, [load])

  if (!data) return <Skeleton className="h-64" />
  return (
    <div className="space-y-6">
      <Alert tone="accent" title="All optional">
        The app works without any of these. Keys are saved encrypted in the app's config file; you can set them as
        environment variables instead (FINNHUB_API_KEY, …), which then show as "set on server".
      </Alert>
      {data.groups.map((group) => (
        <SourceCard key={group.id} group={group} onSaved={setData} />
      ))}
    </div>
  )
}

function SourceCard({ group, onSaved }: { group: Integrations['groups'][number]; onSaved: (d: Integrations) => void }) {
  const [draft, setDraft] = useState<Record<string, unknown>>({})
  const [busy, setBusy] = useState<'save' | 'test' | null>(null)
  const dirty = Object.keys(draft).length > 0

  async function save(body: Record<string, unknown> = draft) {
    setBusy('save')
    try {
      onSaved(await updateIntegrations(body))
      setDraft({})
      toast.success(`${group.title} saved`)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  async function test() {
    setBusy('test')
    try {
      toast.success((await testIntegration(group.id)).message)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card>
      <CardHeader title={group.title} description={group.help} icon={ICONS[group.id as keyof typeof ICONS] ?? 'settings'} />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          {group.fields.map((f) => (
            <FieldInput
              key={f.name}
              field={f}
              value={draft[f.name]}
              onChange={(v) => setDraft((d) => ({ ...d, [f.name]: v }))}
              onClear={() => save({ [f.name]: null })}
            />
          ))}
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="secondary" disabled={busy !== null || dirty} onClick={test}>
            {busy === 'test' ? 'Testing…' : 'Test'}
          </Button>
          <Button disabled={!dirty || busy !== null} onClick={() => save()}>
            {busy === 'save' ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

function FieldInput({
  field,
  value,
  onChange,
  onClear,
}: {
  field: IntegrationField
  value: unknown
  onChange: (v: unknown) => void
  onClear: () => void
}) {
  if (field.from_env) {
    return (
      <Field label={field.label} hint="Set by an environment variable on the server.">
        <Input disabled value={field.kind === 'secret' ? '••••••••' : String(field.value ?? '')} />
      </Field>
    )
  }
  if (field.kind === 'bool') {
    return (
      <div className="sm:col-span-2">
        <Switch
          label={field.label}
          checked={value !== undefined ? Boolean(value) : Boolean(field.value)}
          onChange={(v) => onChange(v)}
        />
      </div>
    )
  }
  if (field.kind === 'secret') {
    return (
      <Field
        label={field.label}
        hint={
          field.is_set ? (
            <span>
              Saved{field.last4 ? ` (ends ${field.last4})` : ''}. Type to replace, or{' '}
              <button type="button" className="underline" onClick={onClear}>
                remove
              </button>
              .
            </span>
          ) : (
            'Not set.'
          )
        }
      >
        <SecretInput
          placeholder={field.is_set ? '••••••••' : ''}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      </Field>
    )
  }
  return (
    <Field label={field.label}>
      <Input
        value={value !== undefined ? String(value ?? '') : String(field.value ?? '')}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  )
}
