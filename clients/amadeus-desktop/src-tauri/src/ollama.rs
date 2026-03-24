// ollama.rs — Manages the Ollama local LLM server process
//
// If Ollama is already running (e.g. user installed it globally), we reuse it.
// If not, we attempt to start it via `ollama serve`.

use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::AppHandle;

static OLLAMA_PROCESS: Mutex<Option<Child>> = Mutex::new(None);

const OLLAMA_HEALTH_URL: &str = "http://localhost:11434";

/// Ensure Ollama is running. Starts it if needed.
pub async fn ensure_running(_app: &AppHandle) {
    // Check if already running
    if is_ollama_running().await {
        log::info!("Ollama already running at {}", OLLAMA_HEALTH_URL);
        return;
    }

    log::info!("Ollama not detected — attempting to start via 'ollama serve'");

    // Try to start Ollama
    match Command::new("ollama").arg("serve").spawn() {
        Ok(child) => {
            log::info!("Ollama serve process spawned (PID: {})", child.id());
            let mut guard = OLLAMA_PROCESS.lock().unwrap();
            *guard = Some(child);

            // Wait for startup
            for _ in 0..20 {
                tokio::time::sleep(Duration::from_millis(500)).await;
                if is_ollama_running().await {
                    log::info!("✅ Ollama is ready");
                    return;
                }
            }
            log::warn!("Ollama did not start in time — AI features may be unavailable");
        }
        Err(e) => {
            log::warn!(
                "Could not start Ollama: {}. \
                Please install Ollama from https://ollama.com and pull phi3:mini",
                e
            );
        }
    }
}

/// Kill Ollama if we started it (don't kill user's existing instance).
pub fn stop() {
    let mut guard = OLLAMA_PROCESS.lock().unwrap();
    if let Some(mut child) = guard.take() {
        log::info!("Stopping Ollama process (PID: {})", child.id());
        let _ = child.kill();
    }
}

/// Returns true if Ollama HTTP server responds.
pub async fn is_ollama_running() -> bool {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(1))
        .build()
        .unwrap_or_default();

    client.get(OLLAMA_HEALTH_URL).send().await
        .map(|r| r.status().as_u16() == 200)
        .unwrap_or(false)
}
