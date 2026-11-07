'use client'

import type { ReactNode } from 'react'
import { AppShell } from '@/shell/AppShell'
import { RequireAuth } from '@/shell/session'

export default function ShellLayout({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <AppShell>{children}</AppShell>
    </RequireAuth>
  )
}
