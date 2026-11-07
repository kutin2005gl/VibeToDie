import { AdminFailed } from '@/features/admin-trace/UsagePages'
import { AgentsPage } from '@/features/agents/AgentsPage'
import { agents, analytics, load, provider } from '@/server/admin'

export default async function Page() {
  const result = await load(() => Promise.all([agents(), analytics(7), provider()]))
  if ('error' in result) return <AdminFailed title="Agents" message={result.error} crumbs={null} />
  const [list, report, choice] = result.data
  return <AgentsPage agents={list} stats={report.per_agent} provider={choice} />
}
