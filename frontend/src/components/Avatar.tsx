import type { MockAgent } from '../mocks/agents'
import styles from './Avatar.module.css'

// Avatar chữ cái riêng của Phone Retail (không dùng mascot của Band).
export function Avatar({ agent, size = 24 }: { agent: MockAgent; size?: number }) {
  return (
    <span
      className={styles.avatar}
      title={agent.name}
      style={{ width: size, height: size, background: agent.color, fontSize: size * 0.45 }}
    >
      {agent.name.charAt(0)}
    </span>
  )
}

export function AvatarStack({ agents, max = 4, size = 22 }: { agents: MockAgent[]; max?: number; size?: number }) {
  const shown = agents.slice(0, max)
  const extra = agents.length - shown.length
  return (
    <span className={styles.stack}>
      {shown.map((a) => <Avatar key={a.id} agent={a} size={size} />)}
      {extra > 0 && <span className={styles.more}>+{extra}</span>}
    </span>
  )
}
