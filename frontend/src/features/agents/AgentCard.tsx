import { agentIcons, Bot } from '../../components/icons'
import { useRouter } from 'next/navigation'
import type { AgentInfo } from '../../api/admin'
import { usd } from '../analytics/format'
import { agentLook, departmentsLabel, type AgentStats } from './look'
import styles from './AgentCard.module.css'

export function AgentCard({ agent, stats }: { agent: AgentInfo; stats: AgentStats }) {
  const navigate = useRouter().push
  const open = () => navigate(`/agents/${agent.name}`)
  const Icon = agentIcons[agent.name] ?? Bot
  const { label, color } = agentLook(agent.name)

  return (
    <article
      className={styles.card}
      tabIndex={0}
      role="link"
      aria-label={`Mở agent ${label}`}
      onClick={open}
      onKeyDown={(e) => { if (e.key === 'Enter' && e.target === e.currentTarget) open() }}
    >
      <header>
        <span className={styles.icon} style={{ color }} aria-hidden="true"><Icon size={28} /></span>
        <div className={styles.names}>
          <strong>{label}</strong>
          <code>{agent.name}</code>
        </div>
      </header>
      <p>{agent.description}</p>
      <div className={styles.chips}>
        <span className={styles.chip}>{agent.model_tier}</span>
        <span className={styles.chip}>effort {agent.effort}</span>
        <span className={styles.meta}>{departmentsLabel(agent)}</span>
      </div>
      <dl className={styles.stats}>
        <div><dt>Gọi model</dt><dd>{stats.llm_calls}</dd></div>
        <div><dt>Gọi công cụ</dt><dd>{stats.tool_calls}</dd></div>
        <div><dt>Lỗi</dt><dd>{stats.errors}</dd></div>
        <div><dt>Chi phí</dt><dd>{usd(stats.cost_usd)}</dd></div>
      </dl>
    </article>
  )
}
