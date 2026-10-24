import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { exportTables, type ExportFormat, type ExportTable } from '../lib/exporter'
import { errorMessage } from '../lib/format'
import { toast } from '../lib/toast'
import { Spinner } from './ui'

const FORMATS: Array<{ value: ExportFormat; label: string }> = [
  { value: 'xlsx', label: 'Excel (.xlsx)' },
  { value: 'csv', label: 'CSV' },
  { value: 'pdf', label: 'PDF' },
]

/** "Export" button with CSV / Excel / PDF; `tables` is built lazily on click. */
export default function ExportMenu({
  title,
  subtitle,
  tables,
  disabled,
}: {
  title: string
  subtitle?: string
  tables: () => ExportTable[] | Promise<ExportTable[]>
  disabled?: boolean
}) {
  const { t } = useTranslation('app')
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<ExportFormat | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', close)
    }
  }, [open])

  async function run(format: ExportFormat) {
    setBusy(format)
    try {
      const data = await tables()
      if (!data.some((x) => x.rows.length)) {
        toast.info(t('export.nothing'))
        return
      }
      await exportTables(format, title, data, subtitle)
      setOpen(false)
    } catch (err) {
      toast.error(t('export.failed', { error: errorMessage(err) }))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:border-line-strong hover:text-fg disabled:opacity-50"
      >
        <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />
        </svg>
        {t('export.button')}
      </button>
      {open && (
        <div role="menu" className="absolute end-0 z-30 mt-1 w-56 rounded-lg border border-line bg-surface p-1 shadow-xl">
          {FORMATS.map((f) => (
            <button
              key={f.value}
              type="button"
              role="menuitem"
              disabled={busy != null}
              onClick={() => run(f.value)}
              className="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-start hover:bg-raised disabled:opacity-60"
            >
              <span>
                <span className="block text-sm">{f.label}</span>
                <span className="block text-xs text-faint">{t(`export.hint.${f.value}`)}</span>
              </span>
              {busy === f.value && <Spinner />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
