mod api;
mod config;
mod db;
mod error;
mod extraction;
mod media;

use std::net::SocketAddr;
use std::sync::Arc;

use axum::Router;
use tower_http::cors::{Any, CorsLayer};
use tower_http::trace::TraceLayer;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

use crate::config::AppConfig;
use crate::db::Database;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::new(
            std::env::var("RUST_LOG").unwrap_or_else(|_| "axew_core=debug,tower_http=info".into()),
        ))
        .with(tracing_subscriber::fmt::layer())
        .init();

    let config = AppConfig::from_env();
    let db = Database::new(&config.db_path).await?;

    tracing::info!("Starting AXEW Core v0.1.0 on port {}", config.port);

    let app_state = api::AppState {
        config: config.clone(),
        db: Arc::new(db),
    };

    let app = Router::new()
        .nest("/api", api::router(app_state))
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        )
        .layer(TraceLayer::new_for_http());

    let addr: SocketAddr = format!("127.0.0.1:{}", config.port).parse()?;
    tracing::info!("AXEW Core listening on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
