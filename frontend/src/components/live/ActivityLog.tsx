import { ScrollArea } from '@mantine/core'
import type { LogEntry } from '../../types'
import styles from './ActivityLog.module.css'

const LEVEL_META: Record<string, { label: string; cls: string }> = {
  info:     { label: 'INFO',  cls: 'dimTag' },
  error:    { label: 'ERROR', cls: 'negTag' },
  critical: { label: 'CRIT', cls: 'negTag' },
  warning:  { label: 'WARN', cls: 'amberTag' },
}

function tagFromMessage(msg: string): { label: string; cls: string } {
  const m = msg.toUpperCase()
  if (m.startsWith('BUY'))           return { label: 'EXEC',  cls: 'posTag' }
  if (m.startsWith('SELL'))          return { label: 'EXEC',  cls: 'negTag' }
  if (m.startsWith('=== CYCLE'))     return { label: 'CYCLE', cls: 'dimTag' }
  if (m.includes('ARBITRAT'))        return { label: 'ARB',   cls: 'amberTag' }
  if (m.includes('TECHNICIAN'))      return { label: 'TECH',  cls: 'blueTag' }
  if (m.includes('ANALYST'))         return { label: 'ANLST', cls: 'posTag' }
  if (m.includes('RISK'))            return { label: 'RISK',  cls: 'orangeTag' }
  if (m.includes('MACRO'))           return { label: 'MACRO', cls: 'purpleTag' }
  if (m.includes('ECONOMIST') || m.includes('[ECON]')) return { label: 'ECON', cls: 'amberTag' }
  if (m.includes('GEOPOLIT') || m.includes('[GEO]'))   return { label: 'GEO',  cls: 'negTag' }
  if (m.includes('STOP') || m.includes('DEATH')) return { label: 'SL', cls: 'negTag' }
  if (m.includes('EVAL') || m.includes('CORRECT')) return { label: 'EVAL', cls: 'cyanTag' }
  if (m.includes('SAVE') || m.includes('LESSON'))  return { label: 'MEM',  cls: 'cyanTag' }
  return { label: 'LOG', cls: 'dimTag' }
}

interface Props { entries: LogEntry[] }

export function ActivityLog({ entries }: Props) {
  return (
    <ScrollArea className={styles.wrap} offsetScrollbars>
      {entries.map((e, i) => {
        const tag = tagFromMessage(e.msg)
        return (
          <div key={i} className={styles.row}>
            <span className={`mono ${styles.time}`}>{e.t}</span>
            <span className={`mono ${styles.tag} ${styles[tag.cls]}`}>{tag.label}</span>
            <span className={`mono ${styles.msg}`}>{e.msg}</span>
          </div>
        )
      })}
    </ScrollArea>
  )
}
