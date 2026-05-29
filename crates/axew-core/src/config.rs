#[derive(Debug, Clone)]
pub struct AppConfig {
    pub port: u16,
    pub db_path: String,
    pub cache_dir: String,
    pub clips_dir: String,
    pub ffmpeg_path: String,
    pub ffprobe_path: String,
}

impl AppConfig {
    pub fn from_env() -> Self {
        let home = dirs::home_dir()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();

        Self {
            port: std::env::var("AXEW_PORT")
                .or_else(|_| std::env::var("AXEW_RUST_PORT"))
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(7001),
            db_path: format!("{}/.axew/axew.db", home),
            cache_dir: std::env::var("AXEW_CACHE_DIR")
                .unwrap_or_else(|_| format!("{}/.axew/cache", home)),
            clips_dir: std::env::var("AXEW_CLIPS_DIR")
                .unwrap_or_else(|_| format!("{}/.axew/clips", home)),
            ffmpeg_path: std::env::var("AXEW_FFMPEG_PATH")
                .unwrap_or_else(|_| "ffmpeg".to_string()),
            ffprobe_path: std::env::var("AXEW_FFPROBE_PATH")
                .unwrap_or_else(|_| "ffprobe".to_string()),
        }
    }
}
