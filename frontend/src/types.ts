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

export type ChatIntent = {
  name: 'product_recommendation'
  raw_message: string
  filters: {
    max_price: number | null
    category: string | null
    keywords: string[]
  }
}

export type ChatResponse = {
  session_id: string
  reply: string
  intent: ChatIntent
  recommendations: Product[]
  steps: AgentStep[]
  mode: 'mock' | 'llm'
}

export type ChatStreamStep = {
  agent: string
  label: string
  status: 'running' | 'completed'
  request_id: string
  trace_id: string
}

export type ChatStreamDelta = {
  text: string
  request_id: string
  trace_id: string
}

export type ChatStreamDone = {
  session_id: string
  reply: string
  intent: ChatIntent
  recommendations: Product[]
  steps: AgentStep[]
  mode: 'mock' | 'llm'
  request_id: string
  trace_id: string
}

export type ChatStreamError = {
  code: string
  message: string
  request_id: string
  trace_id: string
}

export type ChatStreamEvent =
  | { event: 'step'; data: ChatStreamStep }
  | { event: 'delta'; data: ChatStreamDelta }
  | { event: 'done'; data: ChatStreamDone }
  | { event: 'error'; data: ChatStreamError }
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
  draft_version: number
  active_version: number
}

export type AdminConnectionTest = {
  ok: boolean
  message: string
  mode: 'mock' | 'llm'
}
