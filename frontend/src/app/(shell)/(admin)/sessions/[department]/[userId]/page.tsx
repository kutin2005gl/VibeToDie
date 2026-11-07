import { AdminFailed, Crumbs, UserRoomsView } from '@/features/admin-trace/UsagePages'
import { listUsers, load, roomsOf } from '@/server/admin'

export default async function Page({ params }: { params: Promise<{ department: string; userId: string }> }) {
  const p = await params
  const department = decodeURIComponent(p.department)
  const userId = decodeURIComponent(p.userId)
  const result = await load(() => Promise.all([roomsOf(userId), listUsers()]))
  if ('error' in result) {
    return <AdminFailed title="Room của nhân viên" message={result.error} crumbs={<Crumbs department={department} />} />
  }
  const [rooms, users] = result.data
  return <UserRoomsView department={department} userId={userId} rooms={rooms} users={users} />
}
