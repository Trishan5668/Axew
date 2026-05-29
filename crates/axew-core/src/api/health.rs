use axum::{extract::State, Json};
use serde_json::{json, Value};
use std::process::Command;

use crate::api::AppState;

pub async fn health_check(State(state): State<AppState>) -> Json<Value> {
    let ffmpeg_ok = Command::new(&state.config.ffmpeg_path)
        .arg("-version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    let ffprobe_ok = Command::new(&state.config.ffprobe_path)
        .arg("-version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false);

    let status = if ffmpeg_ok && ffprobe_ok {
        "ok"
    } else {
        "degraded"
    };

    Json(json!({
        "status": status,
        "service": "axew-core",
        "version": "0.1.0",
        "ffmpeg": ffmpeg_ok,
        "ffprobe": ffprobe_ok,
        "ffmpeg_path": state.config.ffmpeg_path,
        "ffprobe_path": state.config.ffprobe_path
    }))
}
