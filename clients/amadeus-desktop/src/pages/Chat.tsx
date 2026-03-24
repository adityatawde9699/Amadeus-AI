import React, { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Mic, MicOff, Trash2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const API = 'http://127.0.0.1:8765'

// ── JWT helper (dev: use a fixed token from .env) ─────────────────────────────
const TOKEN = import.meta.env.VITE_API_TOKEN ?? 'dev-token'

interface Message {
    id: string
    role: 'user' | 'assistant'
    content: string
    toolUsed?: string
    streaming?: boolean
}

export default function ChatPage() {
    const [messages, setMessages] = useState<Message[]>([
        {
            id: 'welcome',
            role: 'assistant',
            content: "Hello! I'm **Amadeus**, your local AI assistant. I run 100% on your machine — no cloud, no API keys. What can I help you with?",
        },
    ])
    const [input, setInput] = useState('')
    const [loading, setLoading] = useState(false)
    const [recording, setRecording] = useState(false)
    const [sessionId] = useState(() => crypto.randomUUID())

    const bottomRef = useRef<HTMLDivElement>(null)
    const textareaRef = useRef<HTMLTextAreaElement>(null)

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [messages])

    const autoResize = () => {
        const ta = textareaRef.current
        if (!ta) return
        ta.style.height = 'auto'
        ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
    }

    const sendMessage = useCallback(async () => {
        const text = input.trim()
        if (!text || loading) return

        const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: text }
        const aiMsg: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: '',
            streaming: true,
        }

        setMessages(prev => [...prev, userMsg, aiMsg])
        setInput('')
        setLoading(true)
        if (textareaRef.current) textareaRef.current.style.height = 'auto'

        try {
            // Use SSE streaming endpoint
            const url = new URL(`${API}/api/v1/chat/stream`)
            url.searchParams.set('message', text)
            url.searchParams.set('session_id', sessionId)

            const evtSource = new EventSource(url.toString())
            // EventSource doesn't support auth headers — use fetch with ReadableStream instead

            const resp = await fetch(`${API}/api/v1/chat/stream?message=${encodeURIComponent(text)}&session_id=${sessionId}`, {
                headers: { Authorization: `Bearer ${TOKEN}` },
            })

            evtSource.close()

            if (!resp.ok || !resp.body) {
                throw new Error(`HTTP ${resp.status}`)
            }

            const reader = resp.body.getReader()
            const decoder = new TextDecoder()
            let buffer = ''

            while (true) {
                const { done, value } = await reader.read()
                if (done) break

                buffer += decoder.decode(value, { stream: true })
                const lines = buffer.split('\n')
                buffer = lines.pop() ?? ''

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6).trim()
                        if (data === '[DONE]') break
                        try {
                            const parsed = JSON.parse(data)
                            const delta = parsed.delta ?? ''
                            setMessages(prev =>
                                prev.map(m =>
                                    m.id === aiMsg.id
                                        ? { ...m, content: m.content + delta }
                                        : m
                                )
                            )
                        } catch { /* ignore parse errors */ }
                    }
                }
            }

            // Mark streaming complete
            setMessages(prev =>
                prev.map(m => m.id === aiMsg.id ? { ...m, streaming: false } : m)
            )
        } catch (err) {
            // Fallback to regular chat endpoint
            try {
                const resp = await fetch(`${API}/api/v1/chat`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        Authorization: `Bearer ${TOKEN}`,
                    },
                    body: JSON.stringify({ message: text, session_id: sessionId }),
                })
                const data = await resp.json()
                setMessages(prev =>
                    prev.map(m =>
                        m.id === aiMsg.id
                            ? { ...m, content: data.response ?? 'Error getting response', streaming: false, toolUsed: data.tools_used?.[0] }
                            : m
                    )
                )
            } catch {
                setMessages(prev =>
                    prev.map(m =>
                        m.id === aiMsg.id
                            ? { ...m, content: '⚠️ Could not reach Amadeus backend. Please ensure it is running.', streaming: false }
                            : m
                    )
                )
            }
        } finally {
            setLoading(false)
        }
    }, [input, loading, sessionId])

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            sendMessage()
        }
    }

    const clearChat = () => {
        setMessages([{
            id: 'welcome',
            role: 'assistant',
            content: "Chat cleared. What would you like to talk about?",
        }])
    }

    return (
        <div className="chat-page">
            {/* Header */}
            <div className="chat-header">
                <div>
                    <h1>Chat <span className="gradient-text">with Amadeus</span></h1>
                    <p className="text-sm text-muted" style={{ marginTop: 2 }}>
                        Local · Offline · Private — powered by Phi-3 Mini
                    </p>
                </div>
                <button className="btn-icon" onClick={clearChat} title="Clear chat">
                    <Trash2 size={16} />
                </button>
            </div>

            {/* Messages */}
            <div className="chat-messages selectable">
                {messages.map(msg => (
                    <div key={msg.id} className={`message-row ${msg.role}`}>
                        <div className={`avatar ${msg.role === 'assistant' ? 'ai-avatar' : 'user-avatar'}`}>
                            {msg.role === 'assistant' ? '🧠' : '👤'}
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            {msg.toolUsed && (
                                <div className="tool-badge">
                                    ⚡ {msg.toolUsed}
                                </div>
                            )}
                            <div className={`bubble ${msg.streaming ? 'typing-cursor' : ''}`}>
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                    {msg.content || (msg.streaming ? '' : '…')}
                                </ReactMarkdown>
                            </div>
                        </div>
                    </div>
                ))}
                <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="chat-input-area">
                <div className="input-container">
                    <textarea
                        ref={textareaRef}
                        className="chat-textarea"
                        value={input}
                        onChange={e => { setInput(e.target.value); autoResize() }}
                        onKeyDown={handleKeyDown}
                        placeholder="Ask Amadeus anything… (Enter to send, Shift+Enter for new line)"
                        rows={1}
                    />
                    <button
                        className={`btn-voice ${recording ? 'recording' : ''}`}
                        onClick={() => setRecording(r => !r)}
                        title={recording ? 'Stop recording' : 'Voice input'}
                    >
                        {recording ? <MicOff size={16} /> : <Mic size={16} />}
                    </button>
                    <button
                        className="btn-primary"
                        onClick={sendMessage}
                        disabled={!input.trim() || loading}
                        title="Send"
                    >
                        {loading ? <div className="loading-spinner" /> : <Send size={16} />}
                    </button>
                </div>
            </div>
        </div>
    )
}
