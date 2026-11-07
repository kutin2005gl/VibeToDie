import { AdminFailed, Crumbs, departmentName, DepartmentUsersView } from '@/features/admin-trace/UsagePages'
import { listUsers, load, userUsage } from '@/server/admin'

export default async function Page({ params }: { params: Promise<{ department: string }> }) {
  const department = decodeURIComponent((await params).department)
  const result = await load(() => Promise.all([userUsage(department), listUsers()]))
  if ('error' in result) {
    return <AdminFailed title={`Phòng ban ${departmentName(department)}`} message={result.error}
      crumbs={<Crumbs department={department} />} />
  }
  const [usage, users] = result.data
  return <DepartmentUsersView department={department} usage={usage} users={users} />
}
