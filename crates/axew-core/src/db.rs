use anyhow::Result;
use tokio_rusqlite::Connection;

pub struct Database {
    pub conn: Connection,
}

impl Database {
    pub async fn new(path: &str) -> Result<Self> {
        if let Some(parent) = std::path::Path::new(path).parent() {
            std::fs::create_dir_all(parent)?;
        }

        let conn = Connection::open(path).await?;

        conn.call(|c| {
            c.execute_batch(
                "
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS media_cache (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    duration REAL,
                    width INTEGER,
                    height INTEGER,
                    fps REAL,
                    video_codec TEXT,
                    audio_codec TEXT,
                    sample_rate INTEGER,
                    channels INTEGER,
                    bitrate INTEGER,
                    thumbnail_path TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS thumbnails (
                    id TEXT PRIMARY KEY,
                    media_path TEXT NOT NULL,
                    time_seconds REAL NOT NULL,
                    thumbnail_path TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    last_opened_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
            ",
            )?;
            Ok(())
        })
        .await?;

        Ok(Self { conn })
    }
}
