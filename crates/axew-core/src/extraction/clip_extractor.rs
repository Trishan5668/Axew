use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ExtractionStrategy {
    ReencodeSegment,
    SmartCopy,
    ReencodeWithFastStart,
}

impl Default for ExtractionStrategy {
    fn default() -> Self {
        ExtractionStrategy::ReencodeSegment
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractionRequest {
    pub input_path: String,
    pub start_time: f64,
    pub end_time: f64,
    pub output_name: String,
    pub strategy: ExtractionStrategy,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractionResult {
    pub output_path: String,
    pub actual_start: f64,
    pub actual_end: f64,
    pub actual_duration: f64,
    pub strategy_used: ExtractionStrategy,
    pub ffmpeg_command: String,
    pub ffmpeg_stderr: String,
    pub validation: MediaValidation,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MediaValidation {
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

pub struct KeyframeInspector;

impl KeyframeInspector {
    pub fn get_keyframe_times(input_path: &str, ffprobe_bin: &str) -> Result<Vec<f64>> {
        let output = Command::new(ffprobe_bin)
            .args([
                "-v", "quiet",
                "-select_streams", "v:0",
                "-show_entries", "packet=pts_time,flags",
                "-of", "csv=print_section=0",
                input_path,
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .context("Failed to run ffprobe for keyframe inspection")?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(anyhow!("ffprobe keyframe scan failed: {}", stderr));
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut keyframes: Vec<f64> = Vec::new();

        for line in stdout.lines() {
            let parts: Vec<&str> = line.split(',').collect();
            if parts.len() >= 2 {
                let flags = parts[1].trim();
                if flags.contains('K') {
                    if let Ok(pts) = parts[0].trim().parse::<f64>() {
                        keyframes.push(pts);
                    }
                }
            }
        }

        keyframes.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        Ok(keyframes)
    }

    pub fn nearest_keyframe_before(keyframes: &[f64], time: f64) -> f64 {
        match keyframes.binary_search_by(|k| k.partial_cmp(&time).unwrap_or(std::cmp::Ordering::Equal)) {
            Ok(idx) => keyframes[idx],
            Err(idx) => {
                if idx == 0 {
                    keyframes.first().copied().unwrap_or(0.0)
                } else {
                    keyframes[idx - 1]
                }
            }
        }
    }

    pub fn nearest_keyframe_after(keyframes: &[f64], time: f64) -> f64 {
        match keyframes.binary_search_by(|k| k.partial_cmp(&time).unwrap_or(std::cmp::Ordering::Equal)) {
            Ok(idx) => keyframes[idx],
            Err(idx) => {
                if idx >= keyframes.len() {
                    keyframes.last().copied().unwrap_or(time)
                } else {
                    keyframes[idx]
                }
            }
        }
    }

    pub fn is_keyframe_aligned(keyframes: &[f64], time: f64, tolerance_ms: f64) -> bool {
        let tolerance_sec = tolerance_ms / 1000.0;
        keyframes.iter().any(|k| (k - time).abs() <= tolerance_sec)
    }
}

pub struct ClipExtractor {
    ffmpeg_path: String,
    ffprobe_path: String,
    output_dir: PathBuf,
}

impl ClipExtractor {
    pub fn new(ffmpeg_path: &str, ffprobe_path: &str, output_dir: &Path) -> Self {
        std::fs::create_dir_all(output_dir).ok();
        Self {
            ffmpeg_path: ffmpeg_path.to_string(),
            ffprobe_path: ffprobe_path.to_string(),
            output_dir: output_dir.to_path_buf(),
        }
    }

    pub fn extract(&self, req: &ExtractionRequest) -> Result<ExtractionResult> {
        let output_path = self.output_dir.join(&req.output_name);
        let output_path_str = output_path.to_string_lossy().to_string();

        let keyframes = KeyframeInspector::get_keyframe_times(&req.input_path, &self.ffprobe_path)
            .unwrap_or_default();

        let strategy = match &req.strategy {
            ExtractionStrategy::SmartCopy => {
                if KeyframeInspector::is_keyframe_aligned(&keyframes, req.start_time, 50.0) {
                    ExtractionStrategy::SmartCopy
                } else {
                    tracing::info!(
                        "[ClipExtractor] Start time {:.3}s not keyframe-aligned, upgrading to reencode",
                        req.start_time
                    );
                    ExtractionStrategy::ReencodeSegment
                }
            }
            other => other.clone(),
        };

        let duration = req.end_time - req.start_time;
        let start_str = format!("{:.6}", req.start_time);
        let duration_str = format!("{:.6}", duration);

        let (cmd_args, actual_start, actual_end) = match &strategy {
            ExtractionStrategy::ReencodeSegment | ExtractionStrategy::ReencodeWithFastStart => {
                // -ss AFTER -i = frame-accurate seek (slower but correct)
                let args = vec![
                    "-y".to_string(),
                    "-i".to_string(), req.input_path.clone(),
                    "-ss".to_string(), start_str.clone(),
                    "-t".to_string(), duration_str.clone(),
                    "-c:v".to_string(), "libx264".to_string(),
                    "-preset".to_string(), "ultrafast".to_string(),
                    "-crf".to_string(), "18".to_string(),
                    "-c:a".to_string(), "aac".to_string(),
                    "-b:a".to_string(), "192k".to_string(),
                    "-avoid_negative_ts".to_string(), "make_zero".to_string(),
                    "-movflags".to_string(), "+faststart".to_string(),
                    "-reset_timestamps".to_string(), "1".to_string(),
                    output_path_str.clone(),
                ];
                (args, req.start_time, req.end_time)
            }
            ExtractionStrategy::SmartCopy => {
                // -ss BEFORE -i = fast keyframe seek (safe only when keyframe-aligned)
                let kf_start = KeyframeInspector::nearest_keyframe_before(&keyframes, req.start_time);
                let kf_duration = req.end_time - kf_start;
                let kf_start_str = format!("{:.6}", kf_start);
                let kf_duration_str = format!("{:.6}", kf_duration);
                let args = vec![
                    "-y".to_string(),
                    "-ss".to_string(), kf_start_str,
                    "-i".to_string(), req.input_path.clone(),
                    "-t".to_string(), kf_duration_str,
                    "-c".to_string(), "copy".to_string(),
                    "-avoid_negative_ts".to_string(), "make_zero".to_string(),
                    "-reset_timestamps".to_string(), "1".to_string(),
                    "-movflags".to_string(), "+faststart".to_string(),
                    output_path_str.clone(),
                ];
                (args, kf_start, kf_start + kf_duration)
            }
        };

        let full_command = format!("ffmpeg {}", cmd_args.join(" "));
        tracing::info!("[ClipExtractor] Command: {}", full_command);

        let output = Command::new(&self.ffmpeg_path)
            .args(&cmd_args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .context("Failed to execute ffmpeg")?;

        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        tracing::info!("[ClipExtractor] FFmpeg stderr:\n{}", &stderr[..stderr.len().min(2000)]);

        if !output.status.success() {
            return Err(anyhow!(
                "FFmpeg extraction failed (exit code {:?})\nCommand: {}\nStderr: {}",
                output.status.code(),
                full_command,
                &stderr[..stderr.len().min(2000)]
            ));
        }

        let validation = self.validate_output(&output_path_str)?;

        if !validation.is_playable {
            tracing::error!("[ClipExtractor] Output not playable: {:?}", validation);
            return Err(anyhow!(
                "Extraction produced unplayable output: {:?}",
                validation.warnings
            ));
        }

        Ok(ExtractionResult {
            output_path: output_path_str,
            actual_start,
            actual_end,
            actual_duration: validation.duration_seconds,
            strategy_used: strategy,
            ffmpeg_command: full_command,
            ffmpeg_stderr: stderr,
            validation,
        })
    }

    fn validate_output(&self, path: &str) -> Result<MediaValidation> {
        let output = Command::new(&self.ffprobe_path)
            .args([
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                "-show_format",
                path,
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .context("Failed to run ffprobe for validation")?;

        if !output.status.success() {
            return Ok(MediaValidation {
                has_video_stream: false,
                has_audio_stream: false,
                video_codec: String::new(),
                audio_codec: String::new(),
                duration_seconds: 0.0,
                frame_count: 0,
                is_playable: false,
                container_valid: false,
                warnings: vec!["ffprobe validation failed".to_string()],
            });
        }

        let probe: serde_json::Value = serde_json::from_slice(&output.stdout)
            .unwrap_or_else(|_| serde_json::json!({}));

        let mut has_video = false;
        let mut has_audio = false;
        let mut video_codec = String::new();
        let mut audio_codec = String::new();
        let mut frame_count: u64 = 0;
        let mut warnings: Vec<String> = Vec::new();

        if let Some(streams) = probe.get("streams").and_then(|s| s.as_array()) {
            for stream in streams {
                let codec_type = stream.get("codec_type").and_then(|v| v.as_str()).unwrap_or("");
                match codec_type {
                    "video" if !has_video => {
                        has_video = true;
                        video_codec = stream.get("codec_name")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        if let Some(nb) = stream.get("nb_frames").and_then(|v| v.as_str()) {
                            frame_count = nb.parse().unwrap_or(0);
                        }
                    }
                    "audio" if !has_audio => {
                        has_audio = true;
                        audio_codec = stream.get("codec_name")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                    }
                    _ => {}
                }
            }
        }

        let duration = probe.get("format")
            .and_then(|f| f.get("duration"))
            .and_then(|d| d.as_str())
            .and_then(|s| s.parse::<f64>().ok())
            .unwrap_or(0.0);

        if !has_video {
            warnings.push("No video stream in output".to_string());
        }
        if !has_audio {
            warnings.push("No audio stream in output".to_string());
        }
        if duration <= 0.0 {
            warnings.push("Output has zero duration".to_string());
        }

        let container_valid = Path::new(path).exists()
            && std::fs::metadata(path).map(|m| m.len() > 0).unwrap_or(false);

        let is_playable = has_video && has_audio && duration > 0.0 && container_valid;

        Ok(MediaValidation {
            has_video_stream: has_video,
            has_audio_stream: has_audio,
            video_codec,
            audio_codec,
            duration_seconds: duration,
            frame_count,
            is_playable,
            container_valid,
            warnings,
        })
    }
}
