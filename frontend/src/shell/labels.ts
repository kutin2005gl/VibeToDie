// Tên hiển thị dùng được ở cả server lẫn client (session.tsx là module client).

const departmentLabels: Record<string, string> = {
  cskh: 'CSKH',
  executive: 'Ban điều hành',
  it: 'IT',
}

/** Mọi phòng ban, như `DEPARTMENTS` của user-service (mặc định cskh, executive, it). */
export const knownDepartments = Object.keys(departmentLabels)

export function departmentLabel(id: string) {
  return departmentLabels[id] ?? id
}

export function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  const first = words[0].charAt(0)
  const last = words.length > 1 ? words[words.length - 1].charAt(0) : ''
  return (first + last).toUpperCase()
}
