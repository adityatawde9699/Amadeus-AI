import React, { useState } from 'react'
import { CheckCircle, AlertCircle, ExternalLink } from 'lucide-react'

interface SetupPageProps {
    onComplete: () => void
    status: {
        backend: { running: boolean; message: string }
        ollama: { running: boolean; message: string }
    }
}

export default function SetupPage({ onComplete, status }: SetupPageProps) {
    const [clicked, setClicked] = useState(false)

    const ollamaInstalled = status.ollama.running
    const backendReady = status.backend.running
    const allReady = ollamaInstalled && backendReady

    return (
        <div className="setup-page">
            <div className="setup-card">
                <div className="setup-icon">🧠</div>

                <div>
                    <h2 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.02em', marginBottom: 6 }}>
                        Setting up Amadeus AI
                    </h2>
                    <p className="text-muted text-sm">
                        Your AI runs 100% locally — no account, no cloud, no monthly fees.
                    </p>
                </div>

                <div className="setup-steps">
                    {/* Step 1 */}
                    <SetupStep
                        number={1}
                        done={backendReady}
                        title="AI Engine starting…"
                        description="Amadeus backend is loading your tools, memory, and classifier."
                    />

                    {/* Step 2 */}
                    <SetupStep
                        number={2}
                        done={ollamaInstalled}
                        title={ollamaInstalled ? 'Ollama detected ✓' : 'Install Ollama (required)'}
                        description={
                            ollamaInstalled
                                ? 'Local LLM server is running and ready.'
                                : 'Download Ollama to run AI models on your PC.'
                        }
                        actionHref={ollamaInstalled ? undefined : 'https://ollama.com/download'}
                        actionLabel="Download Ollama"
                    />

                    {/* Step 3 */}
                    <SetupStep
                        number={3}
                        done={ollamaInstalled}
                        title={ollamaInstalled ? 'Phi-3 Mini available ✓' : 'Pull your first model'}
                        description={
                            ollamaInstalled
                                ? 'phi3:mini is ready for offline inference.'
                                : 'After installing Ollama, run: ollama pull phi3:mini'
                        }
                        code={ollamaInstalled ? undefined : 'ollama pull phi3:mini'}
                    />
                </div>

                <button
                    className="btn-setup"
                    onClick={() => { setClicked(true); onComplete() }}
                    disabled={clicked}
                >
                    {allReady ? '✓ Everything ready — Open Chat' : 'Continue anyway →'}
                </button>

                {!allReady && (
                    <p className="text-sm text-muted">
                        You can still explore the app. Chat will work once Ollama is running.
                    </p>
                )}
            </div>
        </div>
    )
}

function SetupStep({
    number, done, title, description, actionHref, actionLabel, code,
}: {
    number: number
    done: boolean
    title: string
    description: string
    actionHref?: string
    actionLabel?: string
    code?: string
}) {
    return (
        <div className={`setup-step ${done ? 'done' : ''}`}>
            <div className="step-number">
                {done ? '✓' : number}
            </div>
            <div className="step-text" style={{ flex: 1 }}>
                <h4>{title}</h4>
                <p>{description}</p>
                {code && (
                    <code style={{
                        display: 'block',
                        marginTop: 6,
                        background: 'rgba(0,212,255,0.06)',
                        padding: '4px 10px',
                        borderRadius: 6,
                        fontSize: 12,
                        color: 'var(--accent-cyan)',
                        fontFamily: 'JetBrains Mono, monospace',
                    }}>
                        {code}
                    </code>
                )}
                {actionHref && (
                    <a
                        href={actionHref}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                            marginTop: 6,
                            fontSize: 12,
                            color: 'var(--accent-cyan)',
                            textDecoration: 'none',
                        }}
                    >
                        {actionLabel} <ExternalLink size={11} />
                    </a>
                )}
            </div>
            <div>
                {done
                    ? <CheckCircle size={18} style={{ color: 'var(--accent-green)' }} />
                    : <AlertCircle size={18} style={{ color: 'var(--text-muted)' }} />}
            </div>
        </div>
    )
}
