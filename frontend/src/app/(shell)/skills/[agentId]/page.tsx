import { notFound } from 'next/navigation'
import { AdminFailed } from '@/features/admin-trace/UsagePages'
import { AgentDetailPage } from '@/features/agents/AgentDetailPage'
import { load, myAgentDetail, myAgents } from '@/server/admin'

export default async function Page({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = await params
  if (!/^\d+$/.test(agentId) || !Number.isSafeInteger(Number(agentId))) notFound()
  const result = await load(async () => {
    const list = await myAgents()
    if (!list.some((a) => a.id === Number(agentId))) notFound()
    return myAgentDetail(Number(agentId))
  })
  if ('error' in result) return <AdminFailed title="Agent của tôi" message={result.error} crumbs={null} />
  return <AgentDetailPage agent={result.data.agent} stats={result.data.stats} personal />
}
