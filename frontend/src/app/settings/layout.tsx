'use client'

import type { ReactNode } from 'react'
import { SettingsShell } from '@/features/settings/SettingsShell'
import { RequireAuth } from '@/shell/session'

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <SettingsShell>{children}</SettingsShell>
    </RequireAuth>
  )
}
