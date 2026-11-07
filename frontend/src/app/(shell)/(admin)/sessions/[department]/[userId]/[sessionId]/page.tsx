import { TraceView } from '@/features/admin-trace/TraceView'
import { AdminFailed, Crumbs, userName } from '@/features/admin-trace/UsagePages'
import { listUsers, load, roomDetail } from '@/server/admin'

export default async function Page({ params }: {
  params: Promise<{ department: string; userId: string; sessionId: string }>
}) {
  const p = await params
  const department = decodeURIComponent(p.department)
  const userId = decodeURIComponent(p.userId)
  const result = await load(() => Promise.all([roomDetail(Number(p.sessionId)), listUsers()]))
  if ('error' in result) {
    return <AdminFailed title="Room" message={result.error} crumbs={<Crumbs department={department} />} />
  }
  const [room, users] = result.data
  return <TraceView department={department} userId={userId} userName={userName(users, userId)} room={room} />
}
