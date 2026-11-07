'use client'

import { useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Analytics } from '../../api/admin'
import { Activity, Bot, MessagesSquare, Info, Zap } from '../../components/icons'
import { StatCard } from '../../components/StatCard'
import { seriesColor } from './format'
import { ChartCard, SeriesLegend, axisStyle, tooltipStyle } from './ChartCard'
import { PerAgentSummary } from './PerAgentSummary'
import styles from './Analytics.module.css'

function useHidden() {
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const toggle = (id: string) =>
    setHidden((h) => {
      const n = new Set(h)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  return { hidden, toggle }
}

// Loại event của trace được tính là tin nhắn (khớp MESSAGE_EVENTS của ai-service)
const messageTypes = [
  { id: 'llm_call', label: 'gọi model', color: 'var(--series-1)' },
  { id: 'tool_call', label: 'gọi công cụ', color: 'var(--series-6)' },
  { id: 'tool_result', label: 'kết quả công cụ', color: 'var(--series-7)' },
  { id: 'run_failed', label: 'lượt chạy lỗi', color: 'var(--series-5)' },
]

export function ActivityTab({ data }: { data: Analytics }) {
  const a = useHidden()
  const t = useHidden()
  const s = data.stats
  const agents = data.per_agent.map((x, i) => ({ id: x.agent, name: x.agent, color: seriesColor(i) }))
  const perAgent = data.per_day.map((d) => ({ day: d.day, ...d.by_agent }))
  const perType = data.per_day.map((d) => ({ day: d.day, ...d.by_type }))
  const perDay = data.per_day.map((d) => ({ day: d.day, total: d.events }))
  return (
    <>
      <div className={styles.stats}>
        <StatCard icon={<Bot size={13} />} label="Agent hoạt động" value={s.agents} />
        <StatCard icon={<MessagesSquare size={13} />} label="Phiên" value={s.rooms} />
        <StatCard icon={<Zap size={13} />} label="Lượt chạy" value={s.runs} />
        <StatCard icon={<Activity size={13} />} label="Gọi model" value={s.llm_calls} />
        <StatCard icon={<Zap size={13} />} label="Gọi công cụ" value={s.tool_calls} />
        <StatCard icon={<Info size={13} />} label="Lỗi" value={s.errors} note="công cụ lỗi + lượt chạy lỗi" />
      </div>

      <div className={styles.grid2}>
        <ChartCard
          title="Tin nhắn theo agent"
          legend={<SeriesLegend items={agents.map((x) => ({ id: x.id, label: x.name, color: x.color }))} hidden={a.hidden} onToggle={a.toggle} />}
        >
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={perAgent}>
              <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
              <XAxis dataKey="day" tick={axisStyle} stroke="var(--border-subtle)" />
              <YAxis tick={axisStyle} stroke="var(--border-subtle)" />
              <Tooltip {...tooltipStyle} />
              {agents.filter((x) => !a.hidden.has(x.id)).map((x) => (
                <Area key={x.id} type="monotone" dataKey={x.id} name={x.name} stackId="1" stroke={x.color} fill={x.color} fillOpacity={0.9} />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard
          title="Tin nhắn theo loại"
          legend={<SeriesLegend items={messageTypes} hidden={t.hidden} onToggle={t.toggle} />}
        >
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={perType}>
              <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
              <XAxis dataKey="day" tick={axisStyle} stroke="var(--border-subtle)" />
              <YAxis tick={axisStyle} stroke="var(--border-subtle)" />
              <Tooltip {...tooltipStyle} />
              {messageTypes.filter((x) => !t.hidden.has(x.id)).map((x) => (
                <Bar key={x.id} dataKey={x.id} name={x.label} stackId="1" fill={x.color} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Tin nhắn theo ngày">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={perDay}>
              <CartesianGrid stroke="var(--border-subtle)" vertical={false} />
              <XAxis dataKey="day" tick={axisStyle} stroke="var(--border-subtle)" />
              <YAxis tick={axisStyle} stroke="var(--border-subtle)" />
              <Tooltip {...tooltipStyle} />
              <Bar dataKey="total" name="Tin nhắn" fill="var(--link)" />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <div className={styles.col}>
          <PerAgentSummary rows={data.per_agent} />
          <section className={styles.chartCard}>
            <h3>Công cụ dùng nhiều</h3>
            <table className={styles.table}>
              <tbody>
                {data.top_tools.map((x) => (
                  <tr key={x.name}><td>{x.name}</td><td className={styles.num}>{x.count}</td></tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      </div>
    </>
  )
}
