import { useMemo, useState } from 'react'
import {
  ArrowUp,
  BadgeCheck,
  Bot,
  ChevronRight,
  CircleHelp,
  Cpu,
  Headphones,
  Laptop,
  LayoutGrid,
  LoaderCircle,
  MessageSquareText,
  Monitor,
  PackageSearch,
  RotateCcw,
  Search,
  Settings2,
  Smartphone,
  Sparkles,
  Star,
  UserRound,
} from 'lucide-react'
import type { AdminConnectionTest, AdminLLMConfig, ChatResponse, Message, Product } from './types'

const quickPrompts = [
  { label: '程序员电脑', text: '推荐一台5000元以内适合程序员的笔记本', icon: Laptop },
  { label: '通勤耳机', text: '帮我选一款适合通勤的降噪耳机', icon: Headphones },
  { label: '桌面升级', text: '推荐一台适合编程和设计的显示器', icon: Monitor },
]

const categoryMeta: Record<string, { icon: typeof Laptop; tone: string }> = {
  Laptop: { icon: Laptop, tone: 'blue' },
  Audio: { icon: Headphones, tone: 'coral' },
  Monitor: { icon: Monitor, tone: 'green' },
  Phone: { icon: Smartphone, tone: 'violet' },
}

const initialMessage: Message = {
  id: 'welcome',
  role: 'assistant',
  content: '你好，我是你的购物研究助手。告诉我预算、使用场景或在意的参数，我会帮你筛选并解释推荐理由。',
}

function App() {
  const [messages, setMessages] = useState<Message[]>([initialMessage])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [modelMode, setModelMode] = useState<ChatResponse['mode']>('mock')
  const [activeCategory, setActiveCategory] = useState('全部商品')
  const [adminOpen, setAdminOpen] = useState(false)
  const [sessionId] = useState(() => `web-${crypto.randomUUID()}`)

  const latestProducts = useMemo(() => {
    const lastRecommendation = [...messages].reverse().find((message) => message.recommendations?.length)
    return lastRecommendation?.recommendations ?? []
  }, [messages])

  const sendMessage = async (text = input) => {
    const message = text.trim()
    if (!message || loading) return
    setInput('')
    setMessages((current) => [...current, { id: crypto.randomUUID(), role: 'user', content: message }])
    setLoading(true)
    try {
      const response = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message }),
      })
      if (!response.ok) throw new Error('服务暂时不可用')
      const data: ChatResponse = await response.json()
      setModelMode(data.mode)
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: 'assistant', content: data.reply, recommendations: data.recommendations, steps: data.steps },
      ])
    } catch {
      setMessages((current) => [...current, { id: crypto.randomUUID(), role: 'assistant', content: '连接服务失败，请确认后端已启动后再试一次。' }])
    } finally {
      setLoading(false)
    }
  }

  const reset = () => {
    setMessages([initialMessage])
    setInput('')
    setModelMode('mock')
    setActiveCategory('全部商品')
  }

  const visibleProducts = latestProducts.filter((product) => activeCategory === '全部商品' || product.category === activeCategory)

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark"><Sparkles size={17} strokeWidth={2.7} /></div>
          <div><strong>SmartCommerce</strong><span>购物决策工作台</span></div>
        </div>
        <div className="topbar-meta"><span className="status-dot" /> Agent 在线 <button className="icon-button" title="帮助"><CircleHelp size={18} /></button></div>
      </header>

      <main className="workspace">
        <aside className="sidebar">
          <div className="side-heading"><span>工作台</span><button className="icon-button" title="新建对话" onClick={reset}><RotateCcw size={17} /></button></div>
          <div className="nav-item active"><MessageSquareText size={17} /> 智能选购 <span className="nav-count">1</span></div>
          <div className="nav-item"><LayoutGrid size={17} /> 商品广场</div>
          <div className="nav-item"><PackageSearch size={17} /> 我的收藏</div>
          <button className={`nav-item nav-button ${adminOpen ? 'active' : ''}`} onClick={() => setAdminOpen(true)}><Settings2 size={17} /> 模型配置</button>
          <div className="sidebar-rule" />
          <div className="side-label">最近对话</div>
          <div className="history-item active-history">程序员电脑怎么选</div>
          <div className="history-item">桌面设备升级清单</div>
          <div className="history-item">周末短途耳机推荐</div>
          <div className="sidebar-foot"><div className="avatar">李</div><div><strong>李咏超</strong><span>个人工作区</span></div><ChevronRight size={15} /></div>
        </aside>

        {adminOpen ? <AdminPanel onClose={() => setAdminOpen(false)} /> : <section className="chat-panel">
          <div className="section-kicker"><span>AI SHOPPING ASSISTANT</span><span className="model-pill"><Cpu size={13} /> {modelMode === 'llm' ? 'DeepSeek' : 'Mock Engine'}</span></div>
          <div className="chat-header"><div><h1>今天想买点什么？</h1><p>从需求出发，帮你找到真正适合的商品。</p></div><div className="header-stat"><strong>{latestProducts.length || 6}</strong><span>候选商品</span></div></div>

          <div className="messages" aria-live="polite">
            {messages.map((message) => <MessageBubble key={message.id} message={message} />)}
            {loading && <div className="message-row assistant-row"><div className="message-avatar"><Bot size={17} /></div><div className="typing"><span /><span /><span /></div></div>}
          </div>

          <div className="composer-area">
            <div className="quick-prompts">{quickPrompts.map(({ label, text, icon: Icon }) => <button key={label} className="quick-prompt" onClick={() => sendMessage(text)}><Icon size={15} />{label}</button>)}</div>
            <form className="composer" onSubmit={(event) => { event.preventDefault(); void sendMessage() }}>
              <textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="描述你的需求，例如：5000元以内，适合编程的笔记本" rows={1} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendMessage() } }} />
              <button className="send-button" type="submit" disabled={!input.trim() || loading} title="发送"><ArrowUp size={19} /></button>
            </form>
            <div className="composer-note"><span>回答基于当前商品数据</span><span>Enter 发送 · Shift + Enter 换行</span></div>
          </div>
        </section>}

        <aside className="insight-panel">
          <div className="insight-title"><div><span className="eyebrow">RECOMMENDATION BOARD</span><h2>推荐结果</h2></div><span className="result-count">{visibleProducts.length} 项</span></div>
          <div className="filter-row">{['全部商品', 'Laptop', 'Audio', 'Monitor'].map((category) => <button key={category} className={activeCategory === category ? 'filter active-filter' : 'filter'} onClick={() => setActiveCategory(category)}>{category === '全部商品' ? '全部' : category}</button>)}</div>
          <div className="product-list">{visibleProducts.length ? visibleProducts.map((product, index) => <ProductCard key={product.id} product={product} featured={index === 0} />) : <div className="empty-board"><Search size={24} /><p>和助手聊聊你的购物需求<br />这里会出现匹配结果</p></div>}</div>
          <div className="board-footer"><BadgeCheck size={16} /><span>推荐会随对话实时更新</span></div>
        </aside>
      </main>
    </div>
  )
}

function AdminPanel({ onClose }: { onClose: () => void }) {
  const [token, setToken] = useState('')
  const [config, setConfig] = useState<AdminLLMConfig>({
    provider: 'mock', api_mode: 'chat', model: 'deepseekflash', base_url: 'https://api.deepseek.com/v1',
    timeout_seconds: 30, max_retries: 2, api_key_configured: false, api_key_masked: null, is_active: true,
  })
  const [apiKey, setApiKey] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  const headers = { 'Content-Type': 'application/json', 'X-Admin-Token': token }
  const payload = () => ({
    provider: config.provider, api_mode: config.api_mode, model: config.model, base_url: config.base_url,
    timeout_seconds: Number(config.timeout_seconds), max_retries: Number(config.max_retries), ...(apiKey ? { api_key: apiKey } : {}),
  })

  const readConfig = async () => {
    setBusy(true)
    try {
      const response = await fetch('/api/v1/admin/llm-config', { headers })
      if (!response.ok) throw new Error('读取配置失败，请检查管理员令牌')
      const data: AdminLLMConfig = await response.json()
      setConfig(data)
      setMessage('配置已读取，API Key 仅显示脱敏结果')
    } catch (error) { setMessage(error instanceof Error ? error.message : '读取配置失败') } finally { setBusy(false) }
  }

  const runAction = async (action: 'save' | 'test' | 'enable') => {
    setBusy(true)
    try {
      const path = action === 'save' ? '/api/v1/admin/llm-config' : action === 'test' ? '/api/v1/admin/llm-config/test' : '/api/v1/admin/llm-config/enable'
      const response = await fetch(path, { method: 'POST', headers, body: action === 'enable' ? undefined : JSON.stringify(payload()) })
      const data = await response.json()
      if (!response.ok) throw new Error(data?.error?.message ?? '操作失败')
      if (action !== 'test') setConfig(data as AdminLLMConfig)
      const result = data as AdminConnectionTest
      setMessage(action === 'test' ? `${result.message}${result.mode === 'mock' ? '，当前使用 Mock' : ''}` : action === 'save' ? '草稿已保存，尚未启用' : '配置已启用，后续请求将使用新配置')
      if (action === 'enable') await readConfig()
    } catch (error) { setMessage(error instanceof Error ? error.message : '操作失败') } finally { setBusy(false) }
  }

  return <section className="admin-panel">
    <div className="admin-header"><div><div className="section-kicker">ADMINISTRATOR CONSOLE</div><h1>模型运行配置</h1><p>在运行期切换 Provider 和调用协议，保存密钥后页面只保留脱敏信息。</p></div><button className="text-button" onClick={onClose}>返回购物助手</button></div>
    <div className="admin-content">
      <div className="admin-auth"><label>管理员令牌<input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="输入服务端 ADMIN_TOKEN" /></label><button className="secondary-button" onClick={() => void readConfig()} disabled={busy || !token}><Settings2 size={15} />读取当前配置</button></div>
      <div className="config-section"><div className="config-label">Provider</div><div className="segmented-control"><button className={config.provider === 'mock' ? 'selected' : ''} onClick={() => setConfig({ ...config, provider: 'mock' })}>Mock Engine</button><button className={config.provider === 'deepseek' ? 'selected' : ''} onClick={() => setConfig({ ...config, provider: 'deepseek' })}>DeepSeek</button></div></div>
      <div className="config-section"><div className="config-label">API 模式</div><div className="segmented-control"><button className={config.api_mode === 'chat' ? 'selected' : ''} onClick={() => setConfig({ ...config, api_mode: 'chat' })}>Chat Completions</button><button className={config.api_mode === 'responses' ? 'selected' : ''} onClick={() => setConfig({ ...config, api_mode: 'responses' })}>Responses</button></div></div>
      <div className="config-grid"><label>模型名称<input value={config.model} onChange={(event) => setConfig({ ...config, model: event.target.value })} /></label><label>Base URL<input value={config.base_url} onChange={(event) => setConfig({ ...config, base_url: event.target.value })} /></label><label>API Key<input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={config.api_key_masked ?? '未配置，Mock 不需要'} /></label><label>超时（秒）<input type="number" min="1" max="300" value={config.timeout_seconds} onChange={(event) => setConfig({ ...config, timeout_seconds: Number(event.target.value) })} /></label><label>最大重试次数<input type="number" min="0" max="5" value={config.max_retries} onChange={(event) => setConfig({ ...config, max_retries: Number(event.target.value) })} /></label></div>
      <div className="admin-actions"><button className="secondary-button" onClick={() => void runAction('test')} disabled={busy || !token}>测试连接</button><button className="secondary-button" onClick={() => void runAction('save')} disabled={busy || !token}>保存草稿</button><button className="primary-button" onClick={() => void runAction('enable')} disabled={busy || !token}>启用配置</button></div>
      {message && <div className="admin-message">{message}</div>}
      <div className="admin-note"><BadgeCheck size={16} /><span>当前配置：{config.is_active ? '已启用' : '草稿'} · API Key 不会返回浏览器</span></div>
    </div>
  </section>
}

function MessageBubble({ message }: { message: Message }) {
  return <div className={`message-row ${message.role === 'user' ? 'user-row' : 'assistant-row'}`}><div className="message-avatar">{message.role === 'user' ? <UserRound size={16} /> : <Bot size={17} />}</div><div className="message-content"><div className="message-meta">{message.role === 'user' ? '你' : 'SmartCommerce Agent'}<span>{message.role === 'assistant' ? '刚刚' : '刚刚'}</span></div><div className="message-bubble">{message.content}</div>{message.steps && <div className="agent-steps">{message.steps.map((step) => <span key={step.agent}><span className="step-check">✓</span>{step.label}</span>)}</div>}</div></div>
}

function ProductCard({ product, featured }: { product: Product; featured: boolean }) {
  const meta = categoryMeta[product.category] ?? categoryMeta.Laptop
  const Icon = meta.icon
  return <article className={`product-card ${featured ? 'featured-card' : ''}`}><div className={`product-visual ${meta.tone}`}><Icon size={36} strokeWidth={1.35} /><span>{product.brand}</span>{featured && <b>TOP PICK</b>}</div><div className="product-body"><div className="product-name-row"><h3>{product.name}</h3><span className="product-price">¥{product.price.toLocaleString()}</span></div><p>{product.description}</p><div className="rating"><Star size={14} fill="currentColor" /><strong>{product.rating}</strong><span>· {product.review_count.toLocaleString()} 条评价</span></div><div className="tag-list">{product.highlights.slice(0, 3).map((highlight) => <span key={highlight}>{highlight}</span>)}</div></div></article>
}

export default App
