use axum::extract::State;
use axum::Json;
use serde::{Deserialize, Serialize};

use crate::api::AppState;
use crate::error::Result;
use crate::extraction::clip_extractor::{
    ClipExtractor, ExtractionRequest, ExtractionStrategy, MediaValidation,
};

#[derive(Debug, Deserialize)]
pub struct ExtractClipPayload {
    pub media_id: String,
    pub input_path: String,
    pub start_time: f64,
    pub end_time: f64,
    pub output_name: String,
    #[serde(default)]
    pub strategy: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct MediaValidationDto {
    pub has_video_stream: bool,
    pub has_audio_stream: bool,
    pub video_codec: String,
    pub audio_codec: String,
    pub duration_seconds: f64,
    pub frame_count: u64,
    pub is_playable: bool,
    pub container_valid: bool,
    pub warnings: Vec<String>,
}

impl From<MediaValidation> for MediaValidationDto {
    fn from(v: MediaValidation) -> Self {
        Self {
            has_video_stream: v.has_video_stream,
            has_audio_stream: v.has_audio_stream,
            video_codec: v.video_codec,
            audio_codec: v.audio_codec,
            duration_seconds: v.duration_seconds,
            frame_count: v.frame_count,
            is_playable: v.is_playable,
            container_valid: v.container_valid,
            warnings: v.warnings,
        }
    }
}

#[derive(Debug, Serialize)]
pub struct ExtractClipResponse {
    pub success: bool,
    pub output_path: Option<String>,
    pub actual_duration: Option<f64>,
    pub ffmpeg_command: Option<String>,
    pub ffmpeg_stderr: Option<String>,
    pub validation: Option<MediaValidationDto>,
    pub error: Option<String>,
}

pub async fn extract_clip(
    State(state): State<AppState>,
    Json(payload): Json<ExtractClipPayload>,
) -> Result<Json<ExtractClipResponse>> {
    let ffmpeg = state.config.ffmpeg_path.clone();
    let ffprobe = state.config.ffprobe_path.clone();
    let output_dir = state.config.clips_dir.clone();

    let strategy = match payload.strategy.as_deref() {
        Some("smart_copy") => ExtractionStrategy::SmartCopy,
        Some("reencode_faststart") => ExtractionStrategy::ReencodeWithFastStart,
        _ => ExtractionStrategy::ReencodeSegment,
    };

    let req = ExtractionRequest {
        input_path: payload.input_path,
        start_time: payload.start_time,
        end_time: payload.end_time,
        output_name: payload.output_name,
        strategy,
    };

    let result = tokio::task::spawn_blocking(move || {
        let extractor = ClipExtractor::new(
            &ffmpeg,
            &ffprobe,
            std::path::Path::new(&output_dir),
        );
        extractor.extract(&req)
    })
    .await
    .map_err(|e| crate::error::AppError::Internal(anyhow::anyhow!("Task join error: {}", e)))?;

    match result {
        Ok(extraction) => Ok(Json(ExtractClipResponse {
            success: true,
            output_path: Some(extraction.output_path),
            actual_duration: Some(extraction.actual_duration),
            ffmpeg_command: Some(extraction.ffmpeg_command),
            ffmpeg_stderr: Some(extraction.ffmpeg_stderr),
            validation: Some(extraction.validation.into()),
            error: None,
        })),
        Err(e) => {
            tracing::error!("[ClipExtractor] Extraction failed: {}", e);
            Ok(Json(ExtractClipResponse {
                success: false,
                output_path: None,
                actual_duration: None,
                ffmpeg_command: Some(format!("{}", e)),
                ffmpeg_stderr: None,
                validation: None,
                error: Some(e.to_string()),
            }))
        }
    }
}
