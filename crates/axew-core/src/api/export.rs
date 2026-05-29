use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use axum::{
    extract::{Path, State},
    Json,
};
use lazy_static::lazy_static;
use serde::{Deserialize, Serialize};

use crate::api::AppState;
use crate::error::{AppError, Result};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportJobRequest {
    pub job_id: String,
    pub input_path: String,
    pub output_path: String,
    pub video_codec: String,
    pub audio_codec: String,
    pub width: u32,
    pub height: u32,
    pub frame_rate: f64,
    pub video_bitrate: u64,
    pub audio_bitrate: u64,
    pub crf: u32,
    pub extra_args: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ExportJobStatus {
    pub job_id: String,
    pub status: String,
    pub progress: f64,
    pub error: Option<String>,
}

type JobMap = Arc<Mutex<HashMap<String, ExportJobStatus>>>;

lazy_static! {
    static ref JOBS: JobMap = Arc::new(Mutex::new(HashMap::new()));
}

pub async fn start_export(
    State(state): State<AppState>,
    Json(req): Json<ExportJobRequest>,
) -> Result<Json<ExportJobStatus>> {
    let job_id = req.job_id.clone();

    {
        let mut jobs = JOBS.lock().unwrap();
        jobs.insert(
            job_id.clone(),
            ExportJobStatus {
                job_id: job_id.clone(),
                status: "running".to_string(),
                progress: 0.0,
                error: None,
            },
        );
    }

    let jobs_clone = JOBS.clone();
    let job_id_clone = job_id.clone();
    let ffmpeg = state.config.ffmpeg_path.clone();

    tokio::task::spawn_blocking(move || {
        let result = crate::media::export_timeline(
            &req.input_path,
            &req.output_path,
            &req.video_codec,
            &req.audio_codec,
            req.width,
            req.height,
            req.frame_rate,
            req.video_bitrate,
            req.audio_bitrate,
            req.crf,
            &req.extra_args,
            &ffmpeg,
            move |progress| {
                let mut jobs = jobs_clone.lock().unwrap();
                if let Some(job) = jobs.get_mut(&job_id_clone) {
                    job.progress = progress;
                }
            },
        );

        let mut jobs = JOBS.lock().unwrap();
        if let Some(job) = jobs.get_mut(&job_id) {
            match result {
                Ok(_) => {
                    job.status = "completed".to_string();
                    job.progress = 100.0;
                }
                Err(e) => {
                    job.status = "failed".to_string();
                    job.error = Some(e.to_string());
                }
            }
        }
    });

    let jobs = JOBS.lock().unwrap();
    let status = jobs
        .get(&req.job_id)
        .cloned()
        .ok_or_else(|| AppError::NotFound("Job not found".to_string()))?;
    Ok(Json(status))
}

pub async fn get_export_status(Path(job_id): Path<String>) -> Result<Json<ExportJobStatus>> {
    let jobs = JOBS.lock().unwrap();
    let status = jobs
        .get(&job_id)
        .cloned()
        .ok_or_else(|| AppError::NotFound(format!("Job {} not found", job_id)))?;
    Ok(Json(status))
}

pub async fn cancel_export(Path(job_id): Path<String>) -> Result<Json<ExportJobStatus>> {
    let mut jobs = JOBS.lock().unwrap();
    let job = jobs
        .get_mut(&job_id)
        .ok_or_else(|| AppError::NotFound(format!("Job {} not found", job_id)))?;
    job.status = "cancelled".to_string();
    Ok(Json(job.clone()))
}
