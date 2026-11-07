import { ChevronDown, Plus, Search } from '../../components/icons'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Avatar } from '../../components/Avatar'
import { useDismiss } from '../../components/useDismiss'
import { agentCatalog, type MockAgentDetail } from '../../mocks/agentCatalog'
import styles from './Pickers.module.css'

type Scope = 'all' | 'local'

function AgentRow({ agent, onPick }: { agent: MockAgentDetail; onPick: (id: string) => void }) {
  return (
    <button className={styles.agentRow} onClick={() => onPick(agent.id)}>
      <Avatar agent={agent} size={22} />
      <span className={styles.agentText}>
        <span className={styles.agentName}>{agent.name}<small>{agent.tag}</small></span>
        <span className={agent.online ? styles.ready : styles.offline}>
          <i />{agent.online ? 'Sẵn sàng · Phone Retail sẽ khởi động' : 'Ngoại tuyến'}
        </span>
      </span>
    </button>
  )
}

// Dropdown "Agent" của ô giao việc: tìm kiếm, lọc phạm vi, agent gần đây và agent của tôi.
// TODO: agent được chọn chưa gửi lên API (backend mới nhận provider); "Chỉ máy này" chưa phân biệt vì mọi agent mock đều chạy cục bộ.
export function AgentPicker({ value, onChange }: { value: string | null; onChange: (id: string | null) => void }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [scope, setScope] = useState<Scope>('all')
  const ref = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useRouter().push
  const close = useCallback(() => setOpen(false), [])
  useDismiss(open, ref, close)

  useEffect(() => {
    if (open) inputRef.current?.focus()
    else setQ('')
  }, [open])

  const selected = agentCatalog.find((a) => a.id === value)
  const matches = agentCatalog.filter((a) => !q || `${a.name} ${a.handle} ${a.tag}`.toLowerCase().includes(q.toLowerCase()))
  const recent = matches.slice(0, 3)
  const others = matches.slice(3)
  const pick = (id: string) => { onChange(id); setOpen(false) }

  return (
    <div ref={ref} className={styles.wrap}>
      <button className={`${styles.trigger} ${open ? styles.open : ''}`} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {selected && <Avatar agent={selected} size={16} />}
        <span>{selected ? selected.name : 'Agent'}</span>
        <ChevronDown size={13} />
      </button>
      {open && (
        <div className={`${styles.panel} ${styles.agentPanel}`} role="dialog" aria-label="Chọn agent">
          <label className={styles.search}>
            <Search size={15} />
            <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm agent…" />
          </label>
          <div className={styles.scopes}>
            <button className={scope === 'all' ? styles.scopeOn : ''} onClick={() => setScope('all')}>Tất cả</button>
            <button className={scope === 'local' ? styles.scopeOn : ''} onClick={() => setScope('local')}>Chỉ máy này</button>
          </div>
          <div className={styles.list}>
            {recent.length > 0 && <div className={styles.section}>Agent gần đây</div>}
            {recent.map((a) => <AgentRow key={a.id} agent={a} onPick={pick} />)}
            {matches.length === 0 && <p className={styles.none}>Không có agent phù hợp.</p>}
            <div className={`${styles.section} ${styles.divider}`}>Agent của tôi</div>
            {others.map((a) => <AgentRow key={a.id} agent={a} onPick={pick} />)}
            <button className={styles.create} onClick={() => { setOpen(false); navigate('/agents') }}>
              <Plus size={14} />Tạo agent…
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
