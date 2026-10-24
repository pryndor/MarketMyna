import { cx } from '../lib/cx'
import { useToastStore } from '../lib/toast'
import { Icon } from './ui'

export function Toaster() {
  const { toasts, dismiss } = useToastStore()
  return (
    <div className="pointer-events-none fixed inset-x-4 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-50 flex sm:start-auto sm:w-80 md:bottom-4 flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className="pointer-events-auto flex items-start gap-3 rounded-lg border border-line-strong bg-raised px-4 py-3 text-sm shadow-xl shadow-black/40"
        >
          <span
            className={cx(
              'mt-0.5',
              t.tone === 'success' ? 'text-up' : t.tone === 'error' ? 'text-down' : 'text-accent-fg',
            )}
          >
            <Icon name={t.tone === 'success' ? 'check' : t.tone === 'error' ? 'alert' : 'bell'} />
          </span>
          <span className="flex-1 break-words">{t.message}</span>
          <button type="button" onClick={() => dismiss(t.id)} className="text-faint hover:text-fg" aria-label="Dismiss">
            <Icon name="x" />
          </button>
        </div>
      ))}
    </div>
  )
}
