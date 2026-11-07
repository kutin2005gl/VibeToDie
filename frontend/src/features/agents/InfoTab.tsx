import type { ReactNode } from 'react'
import type { AgentInfo } from '../../api/admin'
import { tokens, usd, when } from '../analytics/format'
import type { AgentStats } from './look'
import styles from './InfoTab.module.css'

/** Cấu hình lấy từ file mandate; số liệu chạy là của 7 ngày gần nhất. */
export function InfoTab({ agent, stats }: { agent: AgentInfo; stats: AgentStats }) {
  const config: [string, ReactNode][] = [
    ['Hạng model', agent.model_tier],
    ['Mức suy luận', agent.effort],
    ['Model', Object.entries(agent.models).map(([profile, id]) => <span key={profile}>{profile} → {id}</span>)],
    ['Công cụ', agent.tools.length ? agent.tools.join(', ') : 'không có'],
    ['Phần dùng chung', agent.includes.length ? agent.includes.join(', ') : 'không có'],
  ]
  const usage: [string, ReactNode][] = [
    ['Phiên', stats.sessions],
    ['Gọi model', stats.llm_calls],
    ['Gọi công cụ', stats.tool_calls],
    ['Lỗi', stats.errors],
    ['Token', tokens(stats.input_tokens + stats.output_tokens)],
    ['Chi phí', usd(stats.cost_usd)],
    ['Hoạt động cuối', stats.last ? when(stats.last) : 'chưa chạy'],
  ]

  return (
    <div className={styles.wrap}>
      <Section title="Cấu hình" rows={config} />
      <Section title="7 ngày gần nhất" rows={usage} />
    </div>
  )
}

function Section({ title, rows }: { title: string; rows: [string, ReactNode][] }) {
  return (
    <section className={styles.section}>
      <h2>{title}</h2>
      <dl className={styles.list}>
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
    </section>
  )
}
