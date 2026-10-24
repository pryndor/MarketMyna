import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { canonicalZone, deviceTimeZone, downloadMyData, getMe, updateProfile } from '../api/account'
import { Button, Card, CardBody, CardHeader, Field, Input, PageHeader, Segmented, Select } from '../components/ui'
import { cx } from '../lib/cx'
import { errorMessage, initials } from '../lib/format'
import { useSession } from '../lib/session'
import { toast } from '../lib/toast'

// Single-user build: no sign-in, plan or billing. AI keys live under Settings → AI keys.
const TABS = [
  { value: 'profile', label: 'Profile' },
  { value: 'data', label: 'Your data' },
]

export default function AccountPage() {
  const me = useSession((s) => s.me)
  const setMe = useSession((s) => s.setMe)
  const [params, setParams] = useSearchParams()
  const tabs = TABS
  const tab = tabs.some((t) => t.value === params.get('tab')) ? params.get('tab')! : 'profile'

  // Pick up changes made elsewhere (another tab).
  useEffect(() => {
    getMe()
      .then(setMe)
      .catch(() => {})
  }, [setMe])

  if (!me) return null

  return (
    <div className="space-y-6">
      <PageHeader
        title="Account settings"
        description="Your name, time zone and data."
      />
      <Segmented
        options={tabs}
        value={tab}
        onChange={(t) => {
          const next = new URLSearchParams(params)
          next.set('tab', t)
          setParams(next, { replace: true })
        }}
      />
      {tab === 'profile' && <ProfileCard />}
      {tab === 'data' && <DataCard />}
    </div>
  )
}

function ProfileCard() {
  const me = useSession((s) => s.me)!
  const setMe = useSession((s) => s.setMe)
  const [name, setName] = useState(me.name)
  const savedZone = me.timezone ?? 'Asia/Kolkata'
  const savedAuto = me.timezone_auto !== false
  const [zoneName, setZoneName] = useState(savedZone)
  const [zoneAuto, setZoneAuto] = useState(savedAuto)
  const [busy, setBusy] = useState(false)
  const deviceZone = deviceTimeZone()
  const shownZone = zoneAuto && deviceZone ? deviceZone : zoneName
  const zones = useMemo(() => {
    const list = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone').map(canonicalZone) : []
    return [...new Set([zoneName, deviceZone, ...list])].filter(Boolean).sort()
  }, [zoneName, deviceZone])
  async function save(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      setMe(await updateProfile({ name, timezone: shownZone, timezone_auto: zoneAuto }))
      toast.success('Profile saved')
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader title="Profile" icon="user" />
      <CardBody className="space-y-5">
        <div className="flex items-center gap-4">
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-accent-soft text-lg font-semibold text-accent-fg ring-1 ring-accent/30">
            {initials(me.name, me.email)}
          </span>
          <div className="min-w-0">
            <div className="truncate text-base font-semibold">{me.name || 'No name yet'}</div>
          </div>
        </div>
        {/* Top-aligned: the hints under the fields differ in height, so bottom alignment staggers the inputs. The button drops by one label (line + mb-1.5). */}
        <form onSubmit={save} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-start">
          <Field label="Name" hint="Shown in the menu.">
            <Input value={name} maxLength={80} autoComplete="name" onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field
            label={
              <span className="flex items-center justify-between gap-2">
                Time zone
                <ZoneAutoToggle
                  checked={zoneAuto}
                  disabled={!deviceZone}
                  onChange={(next) => {
                    setZoneAuto(next)
                    if (!next && deviceZone) setZoneName(deviceZone)
                  }}
                />
              </span>
            }
            hint={
              zoneAuto
                ? `From this device's clock: now ${localTime(shownZone)}. Changes when you travel.`
                : `Scheduled report times are in this zone: now ${localTime(shownZone)}.`
            }
          >
            {zoneAuto ? (
              <Input value={shownZone.replace(/_/g, ' ')} readOnly aria-readonly className="cursor-default text-muted" />
            ) : (
              <Select
                value={zoneName}
                onChange={(e) => setZoneName(e.target.value)}
                options={zones.map((z) => ({ value: z, label: z.replace(/_/g, ' ') }))}
              />
            )}
          </Field>
          <Button
            type="submit"
            variant="secondary"
            className="sm:mt-[calc(var(--text-xs--line-height)+0.375rem)]"
            loading={busy}
            disabled={name.trim() === me.name.trim() && shownZone === savedZone && zoneAuto === savedAuto}
          >
            Save
          </Button>
        </form>
      </CardBody>
    </Card>
  )
}

/** The current time in a zone, e.g. "2:05 pm IST". */
function localTime(zone: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, { timeZone: zone, hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }).format(new Date())
  } catch {
    return '—'
  }
}

/** Small "Set automatically" switch for the time zone label row. */
function ZoneAutoToggle({ checked, disabled, onChange }: { checked: boolean; disabled?: boolean; onChange: (next: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      title={disabled ? "This browser doesn't share its time zone" : "Follow this device's time zone"}
      onClick={(e) => {
        e.preventDefault()
        onChange(!checked)
      }}
      className="inline-flex items-center gap-1.5 text-xs font-normal text-muted hover:text-fg disabled:opacity-50"
    >
      Set automatically
      <span className={cx('relative h-4 w-7 shrink-0 rounded-full transition-colors', checked ? 'bg-accent' : 'bg-line-strong')}>
        <span
          className={cx(
            'absolute top-0.5 start-0 h-3 w-3 rounded-full bg-white transition-transform',
            checked ? 'translate-x-3.5' : 'translate-x-0.5',
          )}
        />
      </span>
    </button>
  )
}

/** GDPR / DPDP: a copy of everything stored about you, any time. */
function DownloadDataButton() {
  const [busy, setBusy] = useState(false)
  async function go() {
    setBusy(true)
    try {
      await downloadMyData()
      toast.success('Your data file is downloading.')
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button variant="secondary" icon="download" loading={busy} onClick={go}>
      Download my data
    </Button>
  )
}

function DataCard() {
  return (
    <Card>
      <CardHeader
        title="Your data"
        icon="download"
        description="Download a copy of everything MarketMyna stores about you, whenever you like."
      />
      <CardBody className="space-y-3">
        <p className="text-sm text-muted">
          One JSON file with your profile, plan and payments, portfolios and transactions, watchlists, alerts, scheduled
          report settings and usage history. Passwords, login tokens and your saved AI keys are never included.
        </p>
        <DownloadDataButton />
      </CardBody>
    </Card>
  )
}

