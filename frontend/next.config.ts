import type { NextConfig } from 'next'

const config: NextConfig = {
  // Ảnh Docker chỉ cần thư mục .next/standalone, không cần node_modules.
  output: 'standalone',
  // Không sinh AGENTS.md: repo không thêm file .md ngoài README (CLAUDE.md).
  agentRules: false,
}

export default config
