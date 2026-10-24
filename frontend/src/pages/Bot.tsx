import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { getBotCommands, sendBotCommand, type BotCommand } from '../api/bot'
import {
  Button,
  Card,
  CardHeader,
  Icon,
  Input,
  PageHeader,
  Skeleton,
  Spinner,
} from '../components/ui'
import { cx } from '../lib/cx'
import { errorMessage } from '../lib/format'

interface Entry {
  id: number
  role: 'user' | 'bot'
  text: string
  success?: boolean
  at: Date
}

let entryId = 0

/** Commands whose name or alias starts with the typed word come first, then description matches. */
function matches(commands: BotCommand[], word: string): BotCommand[] {
  const w = word.toLowerCase()
  if (!w) return commands
  const starts = commands.filter((c) => c.name.startsWith(w) || c.aliases.some((a) => a.startsWith(w)))
  const rest = commands.filter((c) => !starts.includes(c) && `${c.description} ${c.group}`.toLowerCase().includes(w))
  return [...starts, ...rest]
}

/** The command the input currently names ("/quote AAPL" -> quote). */
function typedCommand(commands: BotCommand[], input: string): BotCommand | undefined {
  const word = input.trim().split(/\s+/)[0]?.replace(/^\//, '').toLowerCase()
  if (!word || !input.includes(' ')) return undefined
  return commands.find((c) => c.name === word || c.aliases.includes(word))
}

export default function BotPage() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [history, setHistory] = useState<string[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [commands, setCommands] = useState<BotCommand[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [menuIndex, setMenuIndex] = useState(0)
  const [menuClosed, setMenuClosed] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const menuRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    getBotCommands()
      .then(setCommands)
      .catch((err) => setLoadError(errorMessage(err)))
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [entries, sending])

  // "/" menu: open while the first word is being typed.
  const slashWord = /^\/\S*$/.test(input) ? input.slice(1) : null
  const menu = useMemo(
    () => (commands && slashWord != null && !menuClosed ? matches(commands, slashWord) : []),
    [commands, slashWord, menuClosed],
  )
  const menuOpen = menu.length > 0
  const active = typedCommand(commands ?? [], input)

  useEffect(() => setMenuIndex(0), [slashWord])
  useEffect(() => {
    menuRef.current?.querySelector(`[data-index="${menuIndex}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [menuIndex])

  const groups = useMemo(() => {
    const out = new Map<string, BotCommand[]>()
    for (const c of commands ?? []) out.set(c.group, [...(out.get(c.group) ?? []), c])
    return [...out.entries()]
  }, [commands])

  function push(entry: Omit<Entry, 'id' | 'at'>) {
    setEntries((prev) => [...prev, { ...entry, id: entryId++, at: new Date() }])
  }

  async function send(text = input) {
    const clean = text.trim()
    if (!clean || sending) return
    push({ role: 'user', text: clean })
    setHistory((h) => [clean, ...h.filter((x) => x !== clean)].slice(0, 50))
    setCursor(null)
    setInput('')
    setSending(true)
    try {
      const result = await sendBotCommand(clean)
      push({ role: 'bot', text: result.text, success: result.success })
    } catch (err) {
      push({ role: 'bot', text: errorMessage(err), success: false })
    } finally {
      setSending(false)
      inputRef.current?.focus()
    }
  }

  /** Fill the command word; a command without arguments runs straight away when `run`. */
  function pick(c: BotCommand, run: boolean) {
    const takesArgs = c.usage.trim().includes(' ')
    if (run && !takesArgs) {
      send(`/${c.name}`)
      return
    }
    setInput(`/${c.name}${takesArgs ? ' ' : ''}`)
    setMenuClosed(true)
    inputRef.current?.focus()
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (menuOpen) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const step = e.key === 'ArrowDown' ? 1 : -1
        setMenuIndex((i) => (i + step + menu.length) % menu.length)
        return
      }
      if (e.key === 'Tab' || e.key === 'Enter') {
        e.preventDefault()
        pick(menu[menuIndex], e.key === 'Enter')
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setMenuClosed(true)
        return
      }
    }
    if (e.key === 'ArrowUp' && history.length) {
      e.preventDefault()
      const next = cursor == null ? 0 : Math.min(cursor + 1, history.length - 1)
      setCursor(next)
      setInput(history[next])
    } else if (e.key === 'ArrowDown' && cursor != null) {
      e.preventDefault()
      const next = cursor - 1
      setCursor(next < 0 ? null : next)
      setInput(next < 0 ? '' : history[next])
    }
  }

  return (
    <div>
      <PageHeader
        title="Bot console"
        description="Every MarketMyna tool as a chat command - the same commands the Telegram bot answers."
        actions={
          entries.length > 0 && (
            <Button variant="ghost" icon="trash" onClick={() => setEntries([])}>
              Clear
            </Button>
          )
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="flex h-[calc(100dvh-19rem-env(safe-area-inset-bottom))] min-h-[360px] flex-col md:h-[calc(100dvh-13rem)] md:min-h-[420px]">
          <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto p-5">
            {entries.length === 0 && (
              <div className="grid h-full place-items-center text-center text-xs text-muted">
                <div>
                  <Icon name="chat" className="mx-auto mb-2 h-5 w-5" />
                  Type <kbd className="rounded bg-raised px-1 font-mono">/</kbd> to see every command, or pick one from the list.
                  <br />
                  <span className="text-faint">↑ / ↓ recalls previous commands · Tab completes</span>
                </div>
              </div>
            )}
            {entries.map((e) => (
              <div key={e.id} className={cx('flex', e.role === 'user' ? 'justify-end' : 'justify-start')}>
                <div className="max-w-[85%]">
                  <pre
                    className={cx(
                      'rounded-xl px-4 py-2.5 font-sans text-sm leading-relaxed whitespace-pre-wrap',
                      e.role === 'user'
                        ? 'rounded-ee-sm bg-accent font-mono text-white'
                        : e.success === false
                          ? 'rounded-es-sm bg-down-soft text-down ring-1 ring-down/30'
                          : 'rounded-es-sm bg-raised',
                    )}
                  >
                    {e.text}
                  </pre>
                  <div className={cx('mt-1 text-xs text-faint', e.role === 'user' && 'text-end')}>
                    {e.at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </div>
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex items-center gap-2 text-xs text-muted">
                <Spinner className="h-3.5 w-3.5" /> Working… AI analysis commands can take a minute.
              </div>
            )}
          </div>

          <div className="relative border-t border-line">
            {menuOpen && (
              <ul
                ref={menuRef}
                role="listbox"
                aria-label="Commands"
                className="absolute end-3 bottom-full start-3 z-20 mb-1 max-h-80 overflow-y-auto rounded-lg border border-line-strong bg-surface py-1 shadow-card"
              >
                {menu.map((c, i) => (
                  <li key={c.name} role="option" aria-selected={i === menuIndex} data-index={i}>
                    <button
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseEnter={() => setMenuIndex(i)}
                      onClick={() => pick(c, false)}
                      className={cx('flex w-full items-baseline gap-3 px-3 py-1.5 text-start', i === menuIndex && 'bg-accent-soft')}
                    >
                      <code className="shrink-0 font-mono text-xs text-accent-fg">{c.usage}</code>
                      <span className="min-w-0 flex-1 truncate text-xs text-muted">{c.description}</span>
                      <span className="hidden shrink-0 text-[11px] text-faint sm:inline">{c.group}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {active && !menuOpen && (
              <div className="px-3 pt-2 text-xs text-muted">
                <code className="font-mono text-accent-fg">{active.usage}</code>
                <span className="text-faint"> · e.g. </span>
                <button type="button" className="font-mono text-faint hover:text-fg" onClick={() => setInput(active.example)}>
                  {active.example}
                </button>
              </div>
            )}
            <form
              className="flex gap-2 p-3"
              onSubmit={(e) => {
                e.preventDefault()
                send()
              }}
            >
              <Input
                ref={inputRef}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value)
                  setCursor(null)
                  setMenuClosed(false)
                }}
                onKeyDown={onKeyDown}
                placeholder="Type / for commands, e.g. /quote RELIANCE"
                className="font-mono"
                role="combobox"
                aria-expanded={menuOpen}
                aria-autocomplete="list"
                autoComplete="off"
                spellCheck={false}
                autoFocus
              />
              <Button type="submit" icon="send" loading={sending} disabled={!input.trim()}>
                Send
              </Button>
            </form>
          </div>
        </Card>

        <Card className="h-fit lg:sticky lg:top-8 lg:max-h-[calc(100vh-4rem)] lg:overflow-y-auto">
          <CardHeader
            title="Commands"
            description={commands ? `${commands.length} commands · click to fill, double-click to run` : 'Click to fill, double-click to run'}
          />
          {loadError ? (
            <p className="px-5 py-4 text-xs text-down">{loadError}</p>
          ) : !commands ? (
            <div className="space-y-2 p-5">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : (
            groups.map(([group, list]) => (
              <div key={group}>
                <div className="border-y border-line bg-canvas px-5 py-1.5 text-[11px] font-semibold tracking-wide text-faint uppercase">
                  {group}
                </div>
                <ul className="divide-y divide-line">
                  {list.map((c) => (
                    <li key={c.name}>
                      <button
                        type="button"
                        title={`e.g. ${c.example}`}
                        onClick={() => {
                          setInput(c.example)
                          setMenuClosed(true)
                          inputRef.current?.focus()
                        }}
                        onDoubleClick={() => send(c.example)}
                        className="w-full px-5 py-2.5 text-start hover:bg-raised/40"
                      >
                        <code className="block font-mono text-xs text-accent-fg">{c.usage}</code>
                        <span className="mt-0.5 block text-xs text-muted">{c.description}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </Card>
      </div>
    </div>
  )
}
