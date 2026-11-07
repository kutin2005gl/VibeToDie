'use client'

import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Analytics } from '../../api/admin'
import { StatCard } from '../../components/StatCard'
import { ChartCard, axisStyle, tooltipStyle } from './ChartCard'
import { tokens, usd, when } from './format'
import styles from './Analytics.module.css'

type Row = { name: string; count: number; tokens: number; cost: number; last: string }

function SessionCostTable({ rows, first, countLabel }: { rows: Row[]; first: string; countLabel: string }) {
  return (
    <table className={styles.table}>
      <thead>
        <tr><th>{first}</th><th className={styles.num}>{countLabel}</th><th className={styles.num}>Token</th><th className={styles.num}>Ước tính</th><th>Hoạt động cuối</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.name}>
            <td>{r.name}</td>
            <td className={styles.num}>{r.count}</td><td className={styles.num}>{tokens(r.tokens)}</td>
            <td className={styles.num}>{usd(r.cost)}</td><td>{when(r.last)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function UsageTab({ data }: { data: Analytics }) {
  const [group, setGroup] = useState<'agents' | 'rooms'>('agents')
  const s = data.stats
  const byAgent: Row[] = data.per_agent.map((a) => ({
    name: a.agent, count: a.sessions, tokens: a.input_tokens + a.output_tokens, cost: a.cost_usd, last: a.last,
  }))
  const byRoom: Row[] = data.per_room.map((r) => ({
    name: r.title, count: r.runs, tokens: r.input_tokens + r.output_tokens, cost: r.cost_usd, last: r.last,
  }))
  return (
    <>
      <p className={styles.muted}>Mức dùng của mọi phiên — {data.days} ngày gần nhất</p>
      <div className={styles.stats3}>
        <StatCard label="Ước tính quy đổi" value={usd(s.cost_usd)} />
        <StatCard label="Tổng token" value={tokens(s.input_tokens + s.output_tokens)} />
        <StatCard label="Mô hình" value={s.models} />
      </div>
      <p className={styles.muted}>
        Ước tính theo giá trong models.json — không phải hoá đơn.
        {s.unpriced_calls > 0 && ` ${s.unpriced_calls} lượt gọi model chưa có giá nên chi phí thật cao hơn.`}
      </p>

      <ChartCard title="Ước tính quy đổi theo ngày">
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data.per_day}>
            <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
            <XAxis dataKey="day" tick={axisStyle} stroke="var(--border-subtle)" />
            <YAxis tick={axisStyle} stroke="var(--border-subtle)" />
            <Tooltip {...tooltipStyle} />
            <Bar dataKey="cost_usd" name="USD" fill="var(--link)" />
          </BarChart>
        </ResponsiveContainer>
      </ChartCard>

      <section className={styles.chartCard}>
        <h3>Ước tính theo mô hình</h3>
        <table className={styles.table}>
          <thead><tr><th>Mô hình</th><th className={styles.num}>Lượt gọi</th><th className={styles.num}>Input</th><th className={styles.num}>Output</th><th className={styles.num}>Ước tính</th></tr></thead>
          <tbody>
            {data.per_model.map((m) => (
              <tr key={m.model}><td>{m.model}</td><td className={styles.num}>{m.calls}</td><td className={styles.num}>{tokens(m.input_tokens)}</td><td className={styles.num}>{tokens(m.output_tokens)}</td><td className={styles.num}>{usd(m.cost_usd)}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className={styles.chartCard}>
        <div className={styles.rowBetween}>
          <h3>Chi phí theo phiên</h3>
          <div className={styles.seg}>
            <button className={group === 'agents' ? styles.segOn : ''} onClick={() => setGroup('agents')}>Agents</button>
            <button className={group === 'rooms' ? styles.segOn : ''} onClick={() => setGroup('rooms')}>Phiên</button>
          </div>
        </div>
        <SessionCostTable
          rows={group === 'agents' ? byAgent : byRoom}
          first={group === 'agents' ? 'Agent' : 'Phiên'}
          countLabel={group === 'agents' ? 'Phiên' : 'Lượt chạy'}
        />
      </section>
    </>
  )
}
