import React, { useEffect, useState } from 'react'
import { HashRouter as Router, Routes, Route, NavLink } from 'react-router-dom'
import { invoke } from '@tauri-apps/api/core'
import { MessageSquare, Cpu, Settings, Zap } from 'lucide-react'
import './index.css'

import ChatPage from './pages/Chat'
import ModelsPage from './pages/Models'
import SettingsPage from './pages/Settings'
import SetupPage from './pages/Setup'

interface SystemStatus {
    backend: { running: boolean; message: string }
    ollama: { running: boolean; message: string }
}

export default function App() {
    const [status, setStatus] = useState<SystemStatus>({
        backend: { running: false, message: 'Starting...' },
        ollama: { running: false, message: 'Checking...' },
    })
    const [setupComplete, setSetupComplete] = useState(false)

    // Poll system status every 3s
    useEffect(() => {
        const poll = async () => {
            try {
                const [backend, ollama] = await Promise.all([
                    invoke<{ running: boolean; message: string }>('get_backend_status'),
                    invoke<{ running: boolean; message: string }>('get_ollama_status'),
                ])
                setStatus({ backend, ollama })
                if (backend.running && ollama.running) setSetupComplete(true)
            } catch (_) {
                // Tauri commands unavailable in browser dev mode
                setSetupComplete(true)
            }
        }
        poll()
        const id = setInterval(poll, 3000)
        return () => clearInterval(id)
    }, [])

    return (
        <Router>
            <div className="app-layout">
                {/* ── Sidebar ── */}
                <aside className="sidebar">
                    <div className="sidebar-logo">
                        <div className="logo-icon">🧠</div>
                        <span>Amadeus</span>
                    </div>

                    <NavLink to="/" end className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                        <MessageSquare size={16} className="nav-icon" />
                        Chat
                    </NavLink>

                    <NavLink to="/models" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                        <Cpu size={16} className="nav-icon" />
                        Models
                    </NavLink>

                    <NavLink to="/settings" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                        <Settings size={16} className="nav-icon" />
                        Settings
                    </NavLink>

                    {/* Status indicators */}
                    <div className="sidebar-bottom">
                        <StatusRow
                            label="AI Engine"
                            running={status.backend.running}
                            message={status.backend.message}
                        />
                        <StatusRow
                            label="Ollama"
                            running={status.ollama.running}
                            message={status.ollama.message}
                        />
                    </div>
                </aside>

                {/* ── Main content ── */}
                <main className="main-content">
                    <Routes>
                        <Route path="/" element={
                            setupComplete
                                ? <ChatPage />
                                : <SetupPage onComplete={() => setSetupComplete(true)} status={status} />
                        } />
                        <Route path="/models" element={<ModelsPage />} />
                        <Route path="/settings" element={<SettingsPage />} />
                    </Routes>
                </main>
            </div>
        </Router>
    )
}

function StatusRow({ label, running, message }: {
    label: string; running: boolean; message: string
}) {
    return (
        <div className="nav-item" style={{ gap: 8, cursor: 'default', fontSize: 12 }} title={message}>
            <div className={`status-dot ${running ? 'online' : 'offline'}`} />
            <span className="text-muted" style={{ flex: 1 }}>{label}</span>
            <Zap size={10} style={{ color: running ? 'var(--accent-green)' : 'var(--text-muted)' }} />
        </div>
    )
}
