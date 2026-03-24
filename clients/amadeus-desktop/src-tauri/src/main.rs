// Amadeus AI — Tauri 2.0 Main Entry Point
//
// This is the Rust app shell. It:
//   1. Spawns the Amadeus FastAPI backend as a child process
//   2. Spawns/checks Ollama server
//   3. Opens the main window once the backend is ready
//   4. Sets up system tray icon with quick actions
//   5. Cleans up child processes on exit

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod commands;
mod ollama;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent,
};

fn main() {
    env_logger::Builder::from_env(
        env_logger::Env::default().default_filter_or("info")
    ).init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_http::init())
        .setup(|app| {
            // ── System tray ────────────────────────────────────────────────
            let quit = MenuItem::with_id(app, "quit", "Quit Amadeus", true, None::<&str>)?;
            let show = MenuItem::with_id(app, "show", "Open Chat", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;

            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "quit" => {
                        log::info!("Quit requested from tray");
                        app.exit(0);
                    }
                    "show" => {
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            // ── Start Ollama (if not already running) ──────────────────────
            let app_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                ollama::ensure_running(&app_handle).await;
            });

            // ── Start Amadeus FastAPI backend ──────────────────────────────
            let app_handle2 = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                match backend::start(&app_handle2).await {
                    Ok(_) => log::info!("Amadeus backend started successfully"),
                    Err(e) => log::error!("Failed to start backend: {}", e),
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_backend_status,
            commands::get_ollama_status,
            commands::list_ollama_models,
            commands::pull_ollama_model,
            commands::open_settings_folder,
        ])
        .on_window_event(|window, event| {
            // Hide to tray instead of closing
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                window.hide().unwrap();
                api.prevent_close();
            }
        })
        .build(tauri::generate_context!())
        .expect("Error building Tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                log::info!("App exiting — cleaning up child processes");
                backend::stop();
                ollama::stop();
            }
        });
}
