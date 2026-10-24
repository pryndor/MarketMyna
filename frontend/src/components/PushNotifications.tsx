import { useCallback, useEffect, useState } from 'react'
import {
  deletePushDevice,
  getVapidPublicKey,
  listPushDevices,
  removePushEndpoint,
  savePushSubscription,
  sendTestPush,
  type PushDevice,
} from '../api/push'
import { errorMessage, relativeTime } from '../lib/format'
import { toast } from '../lib/toast'
import { Alert, Badge, Button, Card, CardBody, CardHeader, Icon } from './ui'

function base64UrlToUint8Array(value: string): Uint8Array<ArrayBuffer> {
  const padded = (value + '='.repeat((4 - (value.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(padded)
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

function deviceLabel(): string {
  const ua = navigator.userAgent
  const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : 'Browser'
  const os = /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Mac OS X/.test(ua) ? 'macOS' : /Windows/.test(ua) ? 'Windows' : /Linux/.test(ua) ? 'Linux' : ''
  return os ? `${browser} on ${os}` : browser
}

const supported =
  typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

/** Browser push: this device's on/off switch plus every registered device. */
export default function PushNotifications() {
  const [devices, setDevices] = useState<PushDevice[] | null>(null)
  const [thisEndpoint, setThisEndpoint] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(
    supported ? Notification.permission : 'unsupported',
  )

  const refresh = useCallback(async () => {
    try {
      setDevices(await listPushDevices())
    } catch (err) {
      toast.error(errorMessage(err))
    }
    if (supported) {
      const reg = await navigator.serviceWorker.getRegistration('/')
      const sub = await reg?.pushManager.getSubscription()
      setThisEndpoint(sub?.endpoint ?? null)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function enable() {
    setBusy(true)
    try {
      const result = await Notification.requestPermission()
      setPermission(result)
      if (result !== 'granted') {
        toast.error('Notifications are blocked for this site. Allow them in the browser’s site settings.')
        return
      }
      const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
      await navigator.serviceWorker.ready
      const key = await getVapidPublicKey()
      let sub = await reg.pushManager.getSubscription()
      if (!sub) {
        sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: base64UrlToUint8Array(key) })
      }
      await savePushSubscription(sub.toJSON(), deviceLabel())
      toast.success('Push notifications enabled on this device')
      await refresh()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function disable() {
    setBusy(true)
    try {
      const reg = await navigator.serviceWorker.getRegistration('/')
      const sub = await reg?.pushManager.getSubscription()
      if (sub) {
        await removePushEndpoint(sub.endpoint)
        await sub.unsubscribe()
      }
      toast.success('Push notifications turned off on this device')
      await refresh()
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function test() {
    setBusy(true)
    try {
      const result = await sendTestPush()
      if (result.sent) toast.success('Test push sent - it should appear in a few seconds')
      else toast.error(result.message)
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const thisDeviceOn = thisEndpoint != null
  const secure = typeof window !== 'undefined' && window.isSecureContext

  return (
    <Card className="mb-6 max-w-3xl">
      <CardHeader
        title="Push notifications"
        description="Get reports and alerts as system notifications from MarketMyna itself, even with the tab closed."
        icon="bell"
        actions={
          devices && devices.length > 0 ? (
            <Button variant="secondary" size="sm" icon="send" loading={busy} onClick={test}>
              Send test
            </Button>
          ) : undefined
        }
      />
      <CardBody className="space-y-4">
        {!supported ? (
          <Alert tone="warn" title="This browser can't receive push notifications">
            Use Chrome, Edge or Firefox on desktop/Android. On iPhone/iPad (iOS 16.4+), open MarketMyna in Safari, tap
            Share → Add to Home Screen, then enable push from the home-screen app.
          </Alert>
        ) : !secure ? (
          <Alert tone="warn" title="Needs HTTPS">
            Browsers only allow push on https:// or http://localhost. Open MarketMyna through HTTPS (e.g. a reverse proxy
            or Tailscale/Cloudflare tunnel) to enable it on other devices.
          </Alert>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line px-4 py-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-medium">
                This device <Badge tone={thisDeviceOn ? 'up' : 'neutral'}>{thisDeviceOn ? 'on' : 'off'}</Badge>
              </div>
              <p className="text-xs text-muted">
                {permission === 'denied'
                  ? 'Notifications are blocked for this site - allow them in the browser’s site settings.'
                  : deviceLabel()}
              </p>
            </div>
            {thisDeviceOn ? (
              <Button variant="ghost" size="sm" loading={busy} onClick={disable}>
                Turn off
              </Button>
            ) : (
              <Button size="sm" icon="bell" loading={busy} disabled={permission === 'denied'} onClick={enable}>
                Enable on this device
              </Button>
            )}
          </div>
        )}

        {devices && devices.length > 0 && (
          <div>
            <span className="mb-1.5 block text-xs font-medium text-muted">Devices receiving push ({devices.length})</span>
            <ul className="divide-y divide-line rounded-lg border border-line">
              {devices.map((d) => (
                <li key={d.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <Icon name="bell" className="h-4 w-4 text-faint" />
                  <span className="min-w-0 flex-1 truncate">{d.label}</span>
                  <span className="hidden text-xs text-faint sm:inline">
                    {d.last_success_at ? `last push ${relativeTime(d.last_success_at)}` : `added ${relativeTime(d.created_at)}`}
                  </span>
                  <button
                    type="button"
                    onClick={async () => {
                      await deletePushDevice(d.id)
                      await refresh()
                    }}
                    className="rounded-md p-1 text-faint hover:bg-down-soft hover:text-down"
                    aria-label={`Remove ${d.label}`}
                  >
                    <Icon name="x" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
