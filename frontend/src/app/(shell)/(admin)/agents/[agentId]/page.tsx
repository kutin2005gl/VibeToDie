import { notFound } from 'next/navigation'
import { AdminFailed } from '@/features/admin-trace/UsagePages'
import { AgentDetailPage } from '@/features/agents/AgentDetailPage'
import { statsOf } from '@/features/agents/look'
import { agents, analytics, load } from '@/server/admin'

export default async function Page({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = await params
  const result = await load(() => Promise.all([agents(), analytics(7)]))
  if ('error' in result) return <AdminFailed title="Agents" message={result.error} crumbs={null} />
  const [list, report] = result.data
  const agent = list.find((a) => a.name === agentId)
  if (!agent) notFound()
  return <AgentDetailPage agent={agent} stats={statsOf(agent.name, report.per_agent)} />
}
