'use client'

import { agentIcons, Bot, ChevronLeft } from '../../components/icons'
import { useState } from 'react'
import Link from 'next/link'
import type { AgentInfo } from '../../api/admin'
import { CopyButton } from '../../components/CopyButton'
import { InfoTab } from './InfoTab'
import { InstructionsTab } from './InstructionsTab'
import { agentLook, departmentsLabel, type AgentStats } from './look'
import styles from './AgentDetailPage.module.css'

type TabId = 'info' | 'instructions'
const tabs: { id: TabId; label: string }[] = [
  { id: 'info', label: 'Cấu hình' },
  { id: 'instructions', label: 'Hướng dẫn' },
]

export function AgentDetailPage({ agent, stats, personal = false }: { agent: AgentInfo; stats: AgentStats; personal?: boolean }) {
  const [tab, setTab] = useState<TabId>('info')
  const Icon = agentIcons[agent.name] ?? Bot
  const { label, color } = agentLook(agent.name)

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link href={personal ? '/skills' : '/agents'} className={styles.back} aria-label="Quay lại danh sách agent"><ChevronLeft size={18} /></Link>
        <span className={styles.icon} style={{ color }} aria-hidden="true"><Icon size={30} /></span>
        <div className={styles.titleBlock}>
          <h1>{label}</h1>
          <div className={styles.ids}>
            <code>{agent.name}</code><CopyButton value={agent.name} label="Sao chép tên mandate" />
          </div>
          <p className={styles.desc}>{agent.description}</p>
          <div className={styles.meta}>
            <span className={styles.tag}>{agent.model_tier}</span>
            <span>{personal ? 'Agent của tôi' : departmentsLabel(agent)}</span>
          </div>
        </div>
      </header>

      <div className={styles.tabs} role="tablist">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? styles.tabOn : ''} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      <div className={styles.content}>
        {tab === 'info' && <InfoTab agent={agent} stats={stats} />}
        {tab === 'instructions' && <InstructionsTab prompt={agent.prompt} personal={personal} />}
      </div>
    </div>
  )
}
