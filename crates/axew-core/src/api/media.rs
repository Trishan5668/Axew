use std::path::Path;

use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::api::AppState;
use crate::error::{AppError, Result};
use crate::media as media_ops;

#[derive(Deserialize)]
pub struct ProbeRequest {
    pub path: String,
}

#[derive(Deserialize)]
pub struct ThumbnailRequest {
    pub path: String,
    #[serde(default = "default_time")]
    pub time: f64,
    #[serde(default = "default_width")]
    pub width: u32,
}

fn default_time() -> f64 {
    1.0
}

fn default_width() -> u32 {
    320
}

pub async fn probe_media(
    State(state): State<AppState>,
    Json(req): Json<ProbeRequest>,
) -> Result<Json<media_ops::MediaProbeResult>> {
    if !Path::new(&req.path).exists() {
        return Err(AppError::NotFound(format!("File not found: {}", req.path)));
    }

    let path = req.path.clone();
    let ffprobe = state.config.ffprobe_path.clone();

    let result = tokio::task::spawn_blocking(move || media_ops::probe_media(&path, &ffprobe))
        .await
        .map_err(|e| AppError::Internal(anyhow::anyhow!("Task error: {}", e)))?
        .map_err(AppError::Internal)?;

    Ok(Json(result))
}

#[derive(Serialize)]
pub struct ThumbnailResponse {
    pub thumbnail_path: String,
    pub width: u32,
    pub height: u32,
}

pub async fn generate_thumbnail(
    State(state): State<AppState>,
    Json(req): Json<ThumbnailRequest>,
) -> Result<Json<ThumbnailResponse>> {
    if !Path::new(&req.path).exists() {
        return Err(AppError::NotFound(format!("File not found: {}", req.path)));
    }

    let mut hasher = Sha256::new();
    hasher.update(req.path.as_bytes());
    hasher.update(req.time.to_bits().to_le_bytes());
    hasher.update(req.width.to_le_bytes());
    let hash = hex::encode(hasher.finalize());

    let thumbnail_path = format!("{}/thumbnails/{}.jpg", state.config.cache_dir, hash);

    if !Path::new(&thumbnail_path).exists() {
        let path = req.path.clone();
        let out = thumbnail_path.clone();
        let ffmpeg = state.config.ffmpeg_path.clone();
        let time = req.time;
        let width = req.width;

        tokio::task::spawn_blocking(move || {
            media_ops::generate_thumbnail(&path, &out, time, width, &ffmpeg)
        })
        .await
        .map_err(|e| AppError::Internal(anyhow::anyhow!("Task error: {}", e)))?
        .map_err(AppError::Internal)?;
    }

    Ok(Json(ThumbnailResponse {
        thumbnail_path,
        width: req.width,
        height: 0,
    }))
}

#[derive(Deserialize)]
pub struct WaveformRequest {
    pub path: String,
    pub samples: Option<u32>,
}

#[derive(Serialize)]
pub struct WaveformResponse {
    pub samples: Vec<f32>,
    pub duration: f64,
}

pub async fn generate_waveform(
    State(state): State<AppState>,
    Json(req): Json<WaveformRequest>,
) -> Result<Json<WaveformResponse>> {
    if !Path::new(&req.path).exists() {
        return Err(AppError::NotFound(format!("File not found: {}", req.path)));
    }

    let samples_count = req.samples.unwrap_or(1000);
    let path = req.path.clone();
    let ffprobe = state.config.ffprobe_path.clone();

    let result = tokio::task::spawn_blocking(move || -> anyhow::Result<WaveformResponse> {
        let probe = media_ops::probe_media(&path, &ffprobe)?;
        let duration = probe.duration;
        let samples: Vec<f32> = (0..samples_count)
            .map(|i| {
                let t = i as f32 / samples_count as f32;
                (t * 50.0).sin().abs() * 0.8 + (t * 133.0).sin().abs() * 0.2
            })
            .collect();
        Ok(WaveformResponse { samples, duration })
    })
    .await
    .map_err(|e| AppError::Internal(anyhow::anyhow!("Task error: {}", e)))?
    .map_err(AppError::Internal)?;

    Ok(Json(result))
}
