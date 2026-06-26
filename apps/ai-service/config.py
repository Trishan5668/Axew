from pydantic_settings import BaseSettings
import os


class Settings(BaseSettings):
    port: int = 7002
    host: str = "127.0.0.1"
    models_dir: str = os.path.expanduser("~/.axew/models")
    cache_dir: str = os.path.expanduser("~/.axew/cache")
    ollama_host: str = "http://localhost:11434"
    default_llm_model: str = "llama3"
    default_whisper_model: str = "base"
    device: str = "cpu"
    log_level: str = "info"

    # OpusClip cloud integration
    opusclip_api_key: str = ""
    opusclip_base_url: str = "https://api.opus.pro"
    opusclip_health_timeout_sec: float = 0.8

    # Resource management
    max_models: int = 3
    embed_model: str = "minilm"  # "minilm" (90 MB) or "bge-large" (420 MB)
    cross_model: str = "tiny"  # "tiny" (80 MB), "base" (130 MB), or "large" (440 MB)
    request_timeout_sec: int = 120
    skip_multimodal: bool = True
    skip_sentiment_models: bool = True  # Use heuristic sentiment by default

    class Config:
        env_prefix = "AXEW_"
        env_file = ".env"


settings = Settings()
