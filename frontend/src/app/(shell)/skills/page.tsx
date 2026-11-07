import { AdminFailed } from '@/features/admin-trace/UsagePages'
import { SkillsPage } from '@/features/skills/SkillsPage'
import { load, myAgents } from '@/server/admin'

// Render ở server: danh sách lấy bằng token trong cookie, không qua lần tải thứ hai ở trình duyệt
export default async function Page() {
  const result = await load(myAgents)
  if ('error' in result) return <AdminFailed title="Agent của tôi" message={result.error} crumbs={null} />
  return <SkillsPage agents={result.data} />
}
