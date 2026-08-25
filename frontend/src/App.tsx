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
  Smartphone,
  Sparkles,
  Star,
  UserRound,
} from 'lucide-react'
import type { ChatResponse, Message, Product } from './types'

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
  const [activeCategory, setActiveCategory] = useState('全部商品')
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
          <div className="sidebar-rule" />
          <div className="side-label">最近对话</div>
          <div className="history-item active-history">程序员电脑怎么选</div>
          <div className="history-item">桌面设备升级清单</div>
          <div className="history-item">周末短途耳机推荐</div>
          <div className="sidebar-foot"><div className="avatar">李</div><div><strong>李咏超</strong><span>个人工作区</span></div><ChevronRight size={15} /></div>
        </aside>

        <section className="chat-panel">
          <div className="section-kicker"><span>AI SHOPPING ASSISTANT</span><span className="model-pill"><Cpu size={13} /> Mock Engine</span></div>
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
        </section>

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

function MessageBubble({ message }: { message: Message }) {
  return <div className={`message-row ${message.role === 'user' ? 'user-row' : 'assistant-row'}`}><div className="message-avatar">{message.role === 'user' ? <UserRound size={16} /> : <Bot size={17} />}</div><div className="message-content"><div className="message-meta">{message.role === 'user' ? '你' : 'SmartCommerce Agent'}<span>{message.role === 'assistant' ? '刚刚' : '刚刚'}</span></div><div className="message-bubble">{message.content}</div>{message.steps && <div className="agent-steps">{message.steps.map((step) => <span key={step.agent}><span className="step-check">✓</span>{step.label}</span>)}</div>}</div></div>
}

function ProductCard({ product, featured }: { product: Product; featured: boolean }) {
  const meta = categoryMeta[product.category] ?? categoryMeta.Laptop
  const Icon = meta.icon
  return <article className={`product-card ${featured ? 'featured-card' : ''}`}><div className={`product-visual ${meta.tone}`}><Icon size={36} strokeWidth={1.35} /><span>{product.brand}</span>{featured && <b>TOP PICK</b>}</div><div className="product-body"><div className="product-name-row"><h3>{product.name}</h3><span className="product-price">¥{product.price.toLocaleString()}</span></div><p>{product.description}</p><div className="rating"><Star size={14} fill="currentColor" /><strong>{product.rating}</strong><span>· {product.review_count.toLocaleString()} 条评价</span></div><div className="tag-list">{product.highlights.slice(0, 3).map((highlight) => <span key={highlight}>{highlight}</span>)}</div></div></article>
}

export default App
