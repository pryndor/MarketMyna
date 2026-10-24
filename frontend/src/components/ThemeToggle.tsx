import { useTranslation } from 'react-i18next'
import { Icon } from './ui'
import { cx } from '../lib/cx'
import { setTheme, useTheme } from '../lib/theme'

/** Sun / moon button that flips between light and dark mode. Used in the app bar and the public pages' header. */
export default function ThemeToggle({ className }: { className?: string }) {
  const { t } = useTranslation()
  const theme = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  const label = next === 'dark' ? t('theme.toDark') : t('theme.toLight')
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className={cx('rounded-lg p-2 text-muted transition-colors hover:bg-raised hover:text-fg', className)}
      title={label}
      aria-label={label}
    >
      <Icon name={theme === 'dark' ? 'sun' : 'moon'} className="h-[18px] w-[18px]" />
    </button>
  )
}
