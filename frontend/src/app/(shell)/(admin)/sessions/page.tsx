import { AdminFailed, Crumbs, DepartmentsView } from '@/features/admin-trace/UsagePages'
import { departmentUsage, listUsers, load } from '@/server/admin'

export default async function Page() {
  const result = await load(() => Promise.all([departmentUsage(), listUsers()]))
  if ('error' in result) return <AdminFailed title="Phiên làm việc" message={result.error} crumbs={<Crumbs />} />
  const [usage, users] = result.data
  return <DepartmentsView usage={usage} users={users} />
}
