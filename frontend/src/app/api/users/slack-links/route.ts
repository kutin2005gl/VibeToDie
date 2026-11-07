import type { NextRequest } from 'next/server'
import { crossOrigin, errorJson, proxy } from '../../../../server/bff'

// This file shadows the catch-all proxy for this exact path, so every method used must be here.
async function handle(req: NextRequest) {
  if (crossOrigin(req)) return errorJson(403, 'cross-origin request')
  const res = await proxy(req, '/api/users/slack-links')
  // Linking codes grant account access and must never be cached.
  res.headers.set('Cache-Control', 'no-store')
  return res
}

export { handle as GET, handle as POST, handle as DELETE }
