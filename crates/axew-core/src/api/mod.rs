pub mod clip;
pub mod export;
pub mod health;
pub mod media;

use std::sync::Arc;

use axum::{routing::get, routing::post, Router};

use crate::config::AppConfig;
use crate::db::Database;

#[derive(Clone)]
pub struct AppState {
    pub config: AppConfig,
    pub db: Arc<Database>,
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health::health_check))
        .route("/media/probe", post(media::probe_media))
        .route("/media/thumbnail", post(media::generate_thumbnail))
        .route("/media/waveform", post(media::generate_waveform))
        .route("/media/extract-clip", post(clip::extract_clip))
        .route("/export/start", post(export::start_export))
        .route("/export/status/:job_id", get(export::get_export_status))
        .route("/export/cancel/:job_id", post(export::cancel_export))
        .with_state(state)
}
