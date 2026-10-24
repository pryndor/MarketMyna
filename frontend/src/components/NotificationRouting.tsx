import { useEffect, useState } from 'react'
import { getNotificationRouting, updateNotificationRouting, type NotificationRouting as Routing } from '../api/systemConfig'
import { cx } from '../lib/cx'
import { errorMessage } from '../lib/format'
import { toast } from '../lib/toast'
import { Button, Card, CardBody, CardHeader, Skeleton } from './ui'

/** Which configured channels receive reports, alerts and error notices. */
export default function NotificationRouting() {
  const [data, setData] = useState<Routing | null>(null)
  const [routes, setRoutes] = useState<Record<string, string[]>>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getNotificationRouting()
      .then((d) => {
        setData(d)
        setRoutes(d.routes)
      })
      .catch((err) => toast.error(errorMessage(err)))
  }, [])

  if (!data) return <Skeleton className="h-40 w-full max-w-3xl" />

  const dirty = JSON.stringify(routes) !== JSON.stringify(data.routes)

  function toggle(purpose: string, channel: string) {
    setRoutes((prev) => {
      // An empty route means "all": start from the full list when narrowing.
      const current = prev[purpose]?.length ? prev[purpose] : data!.channels
      const next = current.includes(channel) ? current.filter((c) => c !== channel) : [...current, channel]
      return { ...prev, [purpose]: next.length === data!.channels.length ? [] : next }
    })
  }

  async function save() {
    setSaving(true)
    try {
      const updated = await updateNotificationRouting(routes)
      setData(updated)
      setRoutes(updated.routes)
      toast.success('Routing saved')
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="mt-6 max-w-3xl">
      <CardHeader
        title="Routing"
        description="Choose which channels receive each kind of message. All channels are on by default."
        icon="send"
      />
      <CardBody>
        {data.channels.length === 0 ? (
          <p className="text-xs text-muted">Configure at least one channel above first.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted">
                  <th className="py-2 pe-4 text-start font-medium">Message</th>
                  {data.channels.map((ch) => (
                    <th key={ch} className="px-2 py-2 text-center font-medium capitalize">
                      {ch}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.purposes.map((p) => {
                  const route = routes[p.id] ?? []
                  return (
                    <tr key={p.id}>
                      <td className="py-2.5 pe-4">
                        <div className="font-medium">{p.label}</div>
                        <div className="text-xs text-muted">{p.description}</div>
                      </td>
                      {data.channels.map((ch) => {
                        const on = route.length === 0 || route.includes(ch)
                        return (
                          <td key={ch} className="px-2 py-2.5 text-center">
                            <input
                              type="checkbox"
                              checked={on}
                              onChange={() => toggle(p.id, ch)}
                              aria-label={`${p.label} via ${ch}`}
                              className={cx('h-4 w-4 accent-[var(--color-accent)]')}
                            />
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardBody>
      <footer className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
        <span className="text-xs text-muted">{dirty ? 'Unsaved changes' : 'All changes saved'}</span>
        <Button size="sm" loading={saving} disabled={!dirty} onClick={save}>
          Save routing
        </Button>
      </footer>
    </Card>
  )
}
