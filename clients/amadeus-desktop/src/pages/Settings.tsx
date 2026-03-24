import React, { useState } from 'react'
import { invoke } from '@tauri-apps/api/core'
import { FolderOpen } from 'lucide-react'

interface ToggleProps {
    checked: boolean
    onChange: (v: boolean) => void
}

function Toggle({ checked, onChange }: ToggleProps) {
    return (
        <label className="toggle-switch">
            <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
            <span className="toggle-track" />
        </label>
    )
}

export default function SettingsPage() {
    const [localOnly, setLocalOnly] = useState(true)
    const [groqKey, setGroqKey] = useState('')
    const [geminiKey, setGeminiKey] = useState('')
    const [whisperModel, setWhisperModel] = useState<'tiny' | 'base' | 'small'>('tiny')
    const [voiceEnabled, setVoiceEnabled] = useState(true)
    const [ttsVoice, setTtsVoice] = useState('en-US-JennyNeural')
    const [theme] = useState('Dark Glassmorphism')

    const openFolder = async () => {
        try { await invoke('open_settings_folder') } catch { /* dev mode */ }
    }

    return (
        <div className="settings-page">
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.02em' }}>
                Settings
            </h1>

            {/* AI Mode */}
            <div className="settings-section">
                <h3>AI Mode</h3>

                <div className="setting-row">
                    <div>
                        <p className="setting-label">Local Only Mode</p>
                        <p className="setting-desc">Use only Ollama — never send data to the cloud.</p>
                    </div>
                    <Toggle checked={localOnly} onChange={setLocalOnly} />
                </div>

                {!localOnly && (
                    <>
                        <div className="setting-row">
                            <div>
                                <p className="setting-label">Groq API Key</p>
                                <p className="setting-desc">Cloud fallback when Ollama is busy (free tier).</p>
                            </div>
                            <input
                                type="password"
                                value={groqKey}
                                onChange={e => setGroqKey(e.target.value)}
                                placeholder="gsk_..."
                                style={{
                                    background: 'rgba(255,255,255,0.04)',
                                    border: '1px solid var(--border-subtle)',
                                    borderRadius: 8,
                                    padding: '8px 12px',
                                    color: 'var(--text-primary)',
                                    fontFamily: 'JetBrains Mono, monospace',
                                    fontSize: 13,
                                    width: 220,
                                    outline: 'none',
                                }}
                            />
                        </div>

                        <div className="setting-row">
                            <div>
                                <p className="setting-label">Gemini API Key</p>
                                <p className="setting-desc">Secondary cloud fallback (free tier).</p>
                            </div>
                            <input
                                type="password"
                                value={geminiKey}
                                onChange={e => setGeminiKey(e.target.value)}
                                placeholder="AIza..."
                                style={{
                                    background: 'rgba(255,255,255,0.04)',
                                    border: '1px solid var(--border-subtle)',
                                    borderRadius: 8,
                                    padding: '8px 12px',
                                    color: 'var(--text-primary)',
                                    fontFamily: 'JetBrains Mono, monospace',
                                    fontSize: 13,
                                    width: 220,
                                    outline: 'none',
                                }}
                            />
                        </div>
                    </>
                )}
            </div>

            {/* Voice */}
            <div className="settings-section">
                <h3>Voice</h3>

                <div className="setting-row">
                    <div>
                        <p className="setting-label">Voice Input / Output</p>
                        <p className="setting-desc">Enable microphone and text-to-speech.</p>
                    </div>
                    <Toggle checked={voiceEnabled} onChange={setVoiceEnabled} />
                </div>

                <div className="setting-row">
                    <div>
                        <p className="setting-label">Whisper STT Model</p>
                        <p className="setting-desc">Smaller = faster but less accurate. Tiny is ideal for 4 GB RAM.</p>
                    </div>
                    <select
                        value={whisperModel}
                        onChange={e => setWhisperModel(e.target.value as any)}
                        style={{
                            background: 'var(--bg-elevated)',
                            border: '1px solid var(--border-subtle)',
                            borderRadius: 8,
                            padding: '8px 12px',
                            color: 'var(--text-primary)',
                            fontFamily: 'inherit',
                            fontSize: 13,
                            outline: 'none',
                        }}
                    >
                        <option value="tiny">Tiny (~75 MB) — fastest</option>
                        <option value="base">Base (~140 MB) — balanced</option>
                        <option value="small">Small (~460 MB) — accurate</option>
                    </select>
                </div>

                <div className="setting-row">
                    <div>
                        <p className="setting-label">TTS Voice</p>
                        <p className="setting-desc">Text-to-speech voice for assistant responses.</p>
                    </div>
                    <select
                        value={ttsVoice}
                        onChange={e => setTtsVoice(e.target.value)}
                        style={{
                            background: 'var(--bg-elevated)',
                            border: '1px solid var(--border-subtle)',
                            borderRadius: 8,
                            padding: '8px 12px',
                            color: 'var(--text-primary)',
                            fontFamily: 'inherit',
                            fontSize: 13,
                            outline: 'none',
                        }}
                    >
                        <option value="en-US-JennyNeural">Jenny (US Female)</option>
                        <option value="en-US-GuyNeural">Guy (US Male)</option>
                        <option value="en-GB-SoniaNeural">Sonia (UK Female)</option>
                        <option value="en-IN-NeerjaNeural">Neerja (IN Female)</option>
                    </select>
                </div>
            </div>

            {/* App */}
            <div className="settings-section">
                <h3>Application</h3>

                <div className="setting-row">
                    <div>
                        <p className="setting-label">Appearance</p>
                        <p className="setting-desc">Current theme.</p>
                    </div>
                    <div style={{
                        padding: '6px 12px',
                        borderRadius: 8,
                        border: '1px solid var(--border-glow)',
                        color: 'var(--accent-cyan)',
                        fontSize: 13,
                    }}>
                        {theme}
                    </div>
                </div>

                <div className="setting-row">
                    <div>
                        <p className="setting-label">Data Folder</p>
                        <p className="setting-desc">Where Amadeus stores your conversations and memories.</p>
                    </div>
                    <button
                        className="btn"
                        onClick={openFolder}
                        style={{
                            background: 'rgba(255,255,255,0.04)',
                            border: '1px solid var(--border-subtle)',
                            color: 'var(--text-secondary)',
                            fontSize: 13,
                        }}
                    >
                        <FolderOpen size={14} /> Open
                    </button>
                </div>
            </div>
        </div>
    )
}
