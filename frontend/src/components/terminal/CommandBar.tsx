import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { TextInput } from '@mantine/core'
import styles from './CommandBar.module.css'

interface Props {
  symbols: string[]
  onSelect: (sym: string) => void
  onAdd: (sym: string) => Promise<boolean> | boolean
}

const FUNCTIONS = [
  { code: 'GP',  desc: 'Graph price' },
  { code: 'DES', desc: 'Description' },
  { code: 'N',   desc: 'News' },
  { code: 'ADD', desc: 'Add to watchlist' },
]

/**
 * Bloomberg-style command line. Type a ticker + Enter to jump to it
 * (adds it to the watchlist if unknown). Optional function suffix:
 *   "AAPL GP"  → graph    "TSLA ADD" → add    "NVDA N" → news
 * Press "/" anywhere to focus, Esc to blur, ↑/↓ to cycle suggestions.
 */
export function CommandBar({ symbols, onSelect, onAdd }: Props) {
  const [value, setValue] = useState('')
  const [focused, setFocused] = useState(false)
  const [flash, setFlash] = useState<{ msg: string; ok: boolean } | null>(null)
  const [hi, setHi] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // global "/" to focus
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '/' && document.activeElement !== inputRef.current) {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const tokens = value.trim().toUpperCase().split(/\s+/).filter(Boolean)
  const query = tokens[0] ?? ''
  const fnCode = tokens[1] ?? ''

  const suggestions = useMemo(() => {
    if (!query) return symbols.slice(0, 8)
    return symbols.filter(s => s.startsWith(query)).slice(0, 8)
  }, [query, symbols])

  const showFn = tokens.length >= 1 && query.length > 0

  const notify = (msg: string, ok: boolean) => {
    setFlash({ msg, ok })
    setTimeout(() => setFlash(null), 2200)
  }

  const run = useCallback(async () => {
    const sym = (suggestions[hi] && query && suggestions[hi].startsWith(query) ? suggestions[hi] : query).toUpperCase()
    if (!sym) return
    const known = symbols.includes(sym)

    if (fnCode === 'ADD' || (!known && fnCode === '')) {
      const ok = await onAdd(sym)
      notify(ok ? `${sym} added` : `${sym} — add failed (max 20 / invalid)`, ok)
      if (ok) onSelect(sym)
    } else if (known) {
      onSelect(sym)
      notify(`${sym} → ${fnCode || 'GP'}`, true)
    } else {
      notify(`${sym} unknown — try "${sym} ADD"`, false)
    }
    setValue('')
    setHi(0)
  }, [suggestions, hi, query, fnCode, symbols, onAdd, onSelect])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') { e.preventDefault(); run() }
    else if (e.key === 'Escape') { setValue(''); inputRef.current?.blur() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setHi(h => Math.min(suggestions.length - 1, h + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi(h => Math.max(0, h - 1)) }
  }

  return (
    <div className={`${styles.bar} ${focused ? styles.barFocus : ''}`}>
      <span className={styles.prompt}>›</span>
      <TextInput
        ref={inputRef}
        variant="unstyled"
        classNames={{ root: styles.inputRoot, input: styles.input }}
        value={value}
        placeholder="COMMAND  ·  type a ticker + Enter   ( / to focus )"
        onChange={(e) => { setValue(e.currentTarget.value); setHi(0) }}
        onKeyDown={onKeyDown}
        onFocus={() => setFocused(true)}
        onBlur={() => setTimeout(() => setFocused(false), 120)}
        spellCheck={false}
        autoComplete="off"
      />

      {flash && (
        <span className={`${styles.flash} ${flash.ok ? styles.flashOk : styles.flashErr}`}>{flash.msg}</span>
      )}

      {focused && (query.length > 0 || suggestions.length > 0) && (
        <div className={styles.dropdown}>
          {suggestions.length > 0 && (
            <div className={styles.ddSection}>
              <div className={styles.ddHd}>SYMBOLS</div>
              {suggestions.map((s, i) => (
                <div
                  key={s}
                  className={`${styles.ddRow} ${i === hi ? styles.ddRowHi : ''}`}
                  onMouseEnter={() => setHi(i)}
                  onMouseDown={(e) => { e.preventDefault(); setValue(s + (fnCode ? ' ' + fnCode : '')); inputRef.current?.focus() }}
                >
                  <span className={styles.ddSym}>{s}</span>
                  <span className={styles.ddKind}>EQUITY</span>
                </div>
              ))}
            </div>
          )}
          {showFn && (
            <div className={styles.ddSection}>
              <div className={styles.ddHd}>FUNCTIONS</div>
              {FUNCTIONS.map(f => (
                <div
                  key={f.code}
                  className={styles.ddRow}
                  onMouseDown={(e) => { e.preventDefault(); setValue(`${query} ${f.code}`); inputRef.current?.focus() }}
                >
                  <span className={styles.ddFn}>{f.code}</span>
                  <span className={styles.ddDesc}>{f.desc}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
