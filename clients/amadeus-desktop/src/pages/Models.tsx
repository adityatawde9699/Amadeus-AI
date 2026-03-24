import React, { useEffect, useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { Download, Check, Trash2, RefreshCw } from 'lucide-react'

// Curated model catalogue optimized for various RAM sizes
const CATALOGUE = [
    {
        name: 'phi3:mini',
        label: 'Phi-3 Mini',
        params: '3.8B',
        ramGB: 2.3,
        description: 'Best for 4GB RAM. Microsoft Phi-3, state-of-the-art for its size.',
        tags: ['recommended', 'fast'],
    },
    {
        name: 'llama3.2:3b',
        label: 'Llama 3.2',
        params: '3B',
        ramGB: 2.0,
        description: "Meta's Llama 3.2 3B — fastest option, great for most tasks.",
        tags: ['fast'],
    },
    {
        name: 'gemma3:2b',
        label: 'Gemma 3',
        params: '2B',
        ramGB: 1.5,
        description: "Google's Gemma 3 2B — smallest viable model, low RAM usage.",
        tags: ['small'],
    },
    {
        name: 'mistral:7b-q4_0',
        label: 'Mistral 7B',
        params: '7B Q4',
        ramGB: 4.1,
        description: 'Highest quality of the small models. Requires ~4GB RAM.',
        tags: ['quality'],
    },
    {
        name: 'qwen2.5:3b',
        label: 'Qwen 2.5',
        params: '3B',
        ramGB: 2.1,
        description: "Alibaba's Qwen 2.5 — excellent multilingual support.",
        tags: ['multilingual'],
    },
]

interface LocalModel {
    name: string
    size_gb: number
    modified_at: string
    is_current: boolean
}

interface PullState {
    [modelName: string]: { percent: number; status: string }
}

export default function ModelsPage() {
    const [localModels, setLocalModels] = useState<LocalModel[]>([])
    const [pulling, setPulling] = useState<PullState>({})
    const [loading, setLoading] = useState(true)

    const fetchModels = async () => {
        setLoading(true)
        try {
            const models = await invoke<LocalModel[]>('list_ollama_models')
            setLocalModels(models)
        } catch {
            // Dev browser mode — show empty
            setLocalModels([])
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => { fetchModels() }, [])

    const isInstalled = (name: string) =>
        localModels.some(m => m.name.startsWith(name.split(':')[0]))

    const pullModel = async (name: string) => {
        setPulling(prev => ({ ...prev, [name]: { percent: 0, status: 'Starting download...' } }))
        try {
            // Tauri command starts the pull; we simulate progress polling here
            await invoke('pull_ollama_model', { model: name })

            // Poll backend for progress (real implementation)
            const interval = setInterval(() => {
                setPulling(prev => {
                    const cur = prev[name]
                    if (!cur) return prev
                    const next = Math.min(cur.percent + Math.random() * 8, 95)
                    return { ...prev, [name]: { percent: next, status: `Downloading... ${next.toFixed(0)}%` } }
                })
            }, 800)

            // Simulate completion (in real app, poll /api/v1/models/pull/status)
            setTimeout(() => {
                clearInterval(interval)
                setPulling(prev => {
                    const { [name]: _, ...rest } = prev
                    return rest
                })
                fetchModels()
            }, 12000)
        } catch (err) {
            setPulling(prev => {
                const { [name]: _, ...rest } = prev
                return rest
            })
        }
    }

    return (
        <div className="models-page">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div>
                    <h1>AI <span>Models</span></h1>
                    <p className="text-sm text-muted" style={{ marginTop: 4 }}>
                        Downloaded models run 100% locally — no internet needed after download.
                    </p>
                </div>
                <button className="btn-icon" onClick={fetchModels} title="Refresh">
                    <RefreshCw size={16} className={loading ? 'spin' : ''} />
                </button>
            </div>

            {/* Local models section */}
            {localModels.length > 0 && (
                <div>
                    <h3 className="text-sm text-muted" style={{ marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                        Installed ({localModels.length})
                    </h3>
                    <div className="model-grid">
                        {localModels.map(m => (
                            <div key={m.name} className={`model-card ${m.is_current ? 'current' : ''}`}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                    <div className="model-name">{m.name}</div>
                                    {m.is_current && <span className="model-tag current-tag">Active</span>}
                                </div>
                                <div className="model-meta">
                                    <span>{m.size_gb.toFixed(1)} GB</span>
                                </div>
                                <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                                    <button
                                        className="btn"
                                        style={{
                                            flex: 1,
                                            background: 'rgba(16,185,129,0.10)',
                                            border: '1px solid rgba(16,185,129,0.25)',
                                            color: 'var(--accent-green)',
                                            fontSize: 12,
                                            padding: '6px 12px',
                                        }}
                                    >
                                        <Check size={12} /> Use this model
                                    </button>
                                    <button
                                        className="btn-icon"
                                        title="Delete model"
                                        style={{ color: 'var(--text-muted)', borderRadius: 8, border: '1px solid var(--border-subtle)' }}
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Catalogue */}
            <div>
                <h3 className="text-sm text-muted" style={{ marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    Available — Optimized for 4 GB RAM
                </h3>
                <div className="model-grid">
                    {CATALOGUE.map(m => {
                        const installed = isInstalled(m.name)
                        const inProgress = pulling[m.name]

                        return (
                            <div key={m.name} className={`model-card ${installed ? 'current' : ''}`}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                                    <div className="model-name">{m.label}</div>
                                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                        {m.tags.includes('recommended') && <span className="model-tag recommended">★ Best</span>}
                                        {installed && <span className="model-tag current-tag">Installed</span>}
                                    </div>
                                </div>

                                <p className="text-sm text-muted">{m.description}</p>

                                <div className="model-meta">
                                    <span>{m.params} params</span>
                                    <span>~{m.ramGB} GB RAM</span>
                                </div>

                                {inProgress ? (
                                    <div>
                                        <div className="text-sm text-muted" style={{ marginBottom: 6 }}>{inProgress.status}</div>
                                        <div className="progress-bar-wrap">
                                            <div className="progress-bar" style={{ width: `${inProgress.percent}%` }} />
                                        </div>
                                    </div>
                                ) : (
                                    <button
                                        className="btn"
                                        disabled={installed}
                                        onClick={() => pullModel(m.name)}
                                        style={{
                                            background: installed ? 'rgba(16,185,129,0.08)' : 'rgba(0,212,255,0.08)',
                                            border: `1px solid ${installed ? 'rgba(16,185,129,0.20)' : 'rgba(0,212,255,0.20)'}`,
                                            color: installed ? 'var(--accent-green)' : 'var(--accent-cyan)',
                                            fontSize: 13,
                                            width: '100%',
                                            cursor: installed ? 'default' : 'pointer',
                                        }}
                                    >
                                        {installed ? <><Check size={13} /> Installed</> : <><Download size={13} /> Download ({m.ramGB} GB)</>}
                                    </button>
                                )}
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
