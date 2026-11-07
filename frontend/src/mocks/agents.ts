// Mock: agent Phone Retail (đề xuất trong band-to-phone-retail-mapping.md §2; danh sách cuối do Owner chốt).
export interface MockAgent {
  id: string
  name: string
  color: string
}

export const agents: MockAgent[] = [
  { id: 'router', name: 'Điều phối', color: 'var(--series-2)' },
  { id: 'advisor', name: 'Tư vấn máy', color: 'var(--series-1)' },
  { id: 'inventory', name: 'Kho hàng', color: 'var(--series-3)' },
  { id: 'pricing', name: 'Giá & khuyến mãi', color: 'var(--series-4)' },
  { id: 'care', name: 'Chăm sóc khách', color: 'var(--series-5)' },
]

export const agentById = (id: string): MockAgent => agents.find((a) => a.id === id) ?? agents[0]
