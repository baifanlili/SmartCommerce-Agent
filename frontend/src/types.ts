export type Product = {
  id: number
  name: string
  category: string
  brand: string
  price: number
  rating: number
  review_count: number
  tags: string[]
  highlights: string[]
  description: string
}

export type AgentStep = {
  agent: string
  label: string
  status: 'completed' | 'running'
}

export type ChatResponse = {
  session_id: string
  reply: string
  recommendations: Product[]
  steps: AgentStep[]
  mode: 'mock' | 'llm'
}

export type Message = {
  id: string
  role: 'user' | 'assistant'
  content: string
  recommendations?: Product[]
  steps?: AgentStep[]
}
