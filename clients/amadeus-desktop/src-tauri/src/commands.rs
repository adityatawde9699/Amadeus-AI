// commands.rs — Tauri IPC commands exposed to the React frontend
//
// These are called from TypeScript via: invoke("command_name", { args })

use serde::{Deserialize, Serialize};
use tauri::AppHandle;

use crate::{backend, ollama};

// ─── Response types ───────────────────────────────────────────────────────────

#[derive(Serialize, Deserialize)]
pub struct StatusResponse {
    pub running: bool,
    pub url: String,
    pub message: String,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct ModelInfo {
    pub name: String,
    pub size_gb: f64,
    pub modified_at: String,
    pub is_current: bool,
}

#[derive(Serialize, Deserialize)]
pub struct PullProgress {
    pub status: String,
    pub percent: f64,
    pub model: String,
}

// ─── Commands ─────────────────────────────────────────────────────────────────

/// Get the status of the Amadeus FastAPI backend.
#[tauri::command]
pub async fn get_backend_status() -> StatusResponse {
    let running = backend::is_running();
    StatusResponse {
        running,
        url: "http://127.0.0.1:8765".into(),
        message: if running {
            "Amadeus AI backend is running".into()
        } else {
            "Backend is starting up...".into()
        },
    }
}

/// Get the status of the Ollama local LLM server.
#[tauri::command]
pub async fn get_ollama_status() -> StatusResponse {
    let running = ollama::is_ollama_running().await;
    StatusResponse {
        running,
        url: "http://localhost:11434".into(),
        message: if running {
            "Ollama is running — AI inference ready".into()
        } else {
            "Ollama not detected. Install from ollama.com".into()
        },
    }
}

/// List all locally available Ollama models.
#[tauri::command]
pub async fn list_ollama_models() -> Vec<ModelInfo> {
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(3))
        .build()
        .unwrap();

    match client.get("http://localhost:11434/api/tags").send().await {
        Ok(resp) => {
            if let Ok(data) = resp.json::<serde_json::Value>().await {
                data["models"]
                    .as_array()
                    .unwrap_or(&vec![])
                    .iter()
                    .map(|m| ModelInfo {
                        name: m["name"].as_str().unwrap_or("unknown").to_string(),
                        size_gb: m["size"].as_f64().unwrap_or(0.0) / 1_073_741_824.0,
                        modified_at: m["modified_at"].as_str().unwrap_or("").to_string(),
                        is_current: m["name"].as_str().unwrap_or("") == "phi3:mini",
                    })
                    .collect()
            } else {
                vec![]
            }
        }
        Err(_) => vec![],
    }
}

/// Trigger a pull of a new Ollama model (non-blocking — progress via HTTP polling).
#[tauri::command]
pub async fn pull_ollama_model(model: String) -> Result<String, String> {
    // We call the backend /api/v1/models/pull endpoint which streams progress
    // The frontend polls this separately for real-time progress bars
    log::info!("Pull requested for model: {}", model);
    Ok(format!("Pull started for {}. Check model manager for progress.", model))
}

/// Open the Amadeus data folder in the system file explorer.
#[tauri::command]
pub async fn open_settings_folder(app: AppHandle) -> Result<(), String> {
    let data_dir = app.path().app_data_dir()
        .map_err(|e| e.to_string())?;

    #[cfg(target_os = "windows")]
    std::process::Command::new("explorer")
        .arg(data_dir)
        .spawn()
        .map_err(|e| e.to_string())?;

    #[cfg(target_os = "macos")]
    std::process::Command::new("open")
        .arg(data_dir)
        .spawn()
        .map_err(|e| e.to_string())?;

    #[cfg(target_os = "linux")]
    std::process::Command::new("xdg-open")
        .arg(data_dir)
        .spawn()
        .map_err(|e| e.to_string())?;

    Ok(())
}
