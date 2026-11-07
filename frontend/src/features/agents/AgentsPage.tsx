'use client'

import { useMemo, useState } from 'react'
import { setProvider, type AgentInfo, type ProviderChoice } from '../../api/admin'
import { PageHeader } from '../../components/PageHeader'
import { CheckFilter } from '../../components/CheckFilter'
import { SearchBar } from '../../components/SearchBar'
import { ProviderSelect } from './ProviderSelect'
import { AgentCard } from './AgentCard'
import { agentLook, statsOf, type AgentStats } from './look'
import styles from './AgentsPage.module.css'

const tiers = ['strong', 'standard', 'cheap'] as const

/** Agent từ file mandate; số liệu chạy là của 7 ngày gần nhất (báo cáo). */
export function AgentsPage({ agents, stats, provider }: { agents: AgentInfo[]; stats: AgentStats[]; provider: ProviderChoice }) {
  const [q, setQ] = useState('')
  const [tier, setTier] = useState<string[]>([])
  const [current, setCurrent] = useState(provider.provider)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Mọi request của hệ thống chạy trên provider này, nên lưu ngay khi chọn
  const choose = async (next: string) => {
    setSaving(true)
    setError(null)
    try {
      setCurrent((await setProvider(next)).provider)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Không lưu được provider')
    } finally {
      setSaving(false)
    }
  }

  const list = useMemo(
    () =>
      agents.filter(
        (a) =>
          (!tier.length || tier.includes(a.model_tier)) &&
          (!q || `${agentLook(a.name).label} ${a.name} ${a.description}`.toLowerCase().includes(q.toLowerCase())),
      ),
    [agents, q, tier],
  )

  return (
    <>
      <PageHeader
        title="Agents"
        actions={
          <div className={styles.provider}>
            <span>Provider của hệ thống</span>
            <ProviderSelect value={current} options={provider.available.includes(current) ? provider.available : [current, ...provider.available]} onChange={(v) => void choose(v)} disabled={saving} />
            {saving && <span role="status">Đang lưu…</span>}
          </div>
        }
      />
      <div className={styles.body}>
        {error && <p className={styles.providerError} role="alert">{error}</p>}
        <SearchBar
          value={q}
          onChange={setQ}
          placeholder="Tìm agent…"
          filters={
            <CheckFilter
              label="Hạng model"
              options={tiers.map((value) => ({ value, count: agents.filter((a) => a.model_tier === value).length }))}
              selected={tier}
              onChange={setTier}
            />
          }
        />
        <section>
          <div className={styles.sectionHead}><h2>Agent</h2><span>{list.length}</span></div>
          <div className={styles.grid}>
            {list.map((a) => <AgentCard key={a.name} agent={a} stats={statsOf(a.name, stats)} />)}
          </div>
          {list.length === 0 && <p className={styles.empty}>Không có agent phù hợp.</p>}
        </section>
      </div>
    </>
  )
}
