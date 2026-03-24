// backend.rs — Manages the Amadeus FastAPI Python backend process
//
// On startup: finds the bundled amadeus-backend binary (or uvicorn in dev),
// spawns it, waits for /health to respond, then signals the UI it's ready.
// On exit: kills the child process cleanly.

use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::Duration;

use tauri::AppHandle;

// Global handle so we can kill the process on app exit
static BACKEND_PROCESS: Mutex<Option<Child>> = Mutex::new(None);

const BACKEND_PORT: u16 = 8765;
const HEALTH_URL: &str = "http://127.0.0.1:8765/health";
const MAX_WAIT_SECS: u64 = 30;
const POLL_INTERVAL_MS: u64 = 500;

/// Start the FastAPI backend and wait until it's healthy.
pub async fn start(app: &AppHandle) -> Result<(), String> {
    log::info!("Starting Amadeus backend on port {}", BACKEND_PORT);

    let binary_path = get_backend_binary_path(app);

    // Build command: either bundled binary or uvicorn dev mode
    let mut cmd = if binary_path.exists() {
        log::info!("Using bundled backend binary: {:?}", binary_path);
        Command::new(&binary_path)
    } else {
        log::warn!(
            "Bundled backend not found at {:?}. Falling back to uvicorn (dev mode).",
            binary_path
        );
        let mut c = Command::new("uvicorn");
        c.args([
            "src.api.server:app",
            "--host", "127.0.0.1",
            "--port", &BACKEND_PORT.to_string(),
            "--workers", "1",
        ]);
        c
    };

    // Set working directory to project root (where src/ lives)
    let project_root = get_project_root(app);
    cmd.current_dir(&project_root);

    // Env vars for the backend
    cmd.env("API_HOST", "127.0.0.1");
    cmd.env("API_PORT", BACKEND_PORT.to_string());
    cmd.env("LOCAL_ONLY_MODE", "true");
    cmd.env("OLLAMA_URL", "http://localhost:11434");
    cmd.env("OLLAMA_MODEL", "phi3:mini");

    // Spawn child process
    let child = cmd.spawn().map_err(|e| format!("Failed to spawn backend: {}", e))?;

    log::info!("Backend process spawned (PID: {})", child.id());

    // Store global handle for cleanup
    {
        let mut guard = BACKEND_PROCESS.lock().unwrap();
        *guard = Some(child);
    }

    // Wait for backend to become healthy
    wait_for_health().await.map_err(|e| format!("Backend health check failed: {}", e))?;

    log::info!("✅ Amadeus backend is healthy at {}", HEALTH_URL);
    Ok(())
}

/// Kill the backend process on app exit.
pub fn stop() {
    let mut guard = BACKEND_PROCESS.lock().unwrap();
    if let Some(mut child) = guard.take() {
        log::info!("Stopping backend process (PID: {})", child.id());
        let _ = child.kill();
    }
}

/// Check if backend process is alive.
pub fn is_running() -> bool {
    let mut guard = BACKEND_PROCESS.lock().unwrap();
    if let Some(child) = guard.as_mut() {
        // try_wait returns Ok(None) if still running
        matches!(child.try_wait(), Ok(None))
    } else {
        false
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// PRIVATE HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/// Poll the backend /health endpoint until it responds or timeout.
async fn wait_for_health() -> Result<(), String> {
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();

    let total_polls = (MAX_WAIT_SECS * 1000) / POLL_INTERVAL_MS;

    for attempt in 0..total_polls {
        tokio::time::sleep(Duration::from_millis(POLL_INTERVAL_MS)).await;

        match client.get(HEALTH_URL).send().await {
            Ok(resp) if resp.status().is_success() => return Ok(()),
            Ok(resp) => {
                log::debug!("Health check attempt {}: HTTP {}", attempt, resp.status());
            }
            Err(e) => {
                log::debug!("Health check attempt {}: {}", attempt, e);
            }
        }
    }

    Err(format!(
        "Backend did not start within {} seconds",
        MAX_WAIT_SECS
    ))
}

fn get_backend_binary_path(app: &AppHandle) -> std::path::PathBuf {
    // In production: binary is in the app's resource directory
    let resource_dir = app.path().resource_dir().unwrap_or_default();
    let ext = if cfg!(target_os = "windows") { ".exe" } else { "" };
    resource_dir.join(format!("amadeus-backend{}", ext))
}

fn get_project_root(app: &AppHandle) -> std::path::PathBuf {
    // In dev: navigate up from src-tauri/ to project root
    if cfg!(debug_assertions) {
        std::env::current_dir().unwrap_or_default()
            .ancestors()
            .find(|p| p.join("src").join("api").join("server.py").exists())
            .unwrap_or(&std::path::Path::new("."))
            .to_path_buf()
    } else {
        app.path().resource_dir().unwrap_or_default()
    }
}
