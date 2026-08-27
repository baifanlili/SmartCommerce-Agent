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

export type AdminLLMConfig = {
  provider: 'mock' | 'deepseek'
  api_mode: 'chat' | 'responses'
  model: string
  base_url: string
  timeout_seconds: number
  max_retries: number
  api_key_configured: boolean
  api_key_masked: string | null
  is_active: boolean
}

export type AdminConnectionTest = {
  ok: boolean
  message: string
  mode: 'mock' | 'llm'
}
