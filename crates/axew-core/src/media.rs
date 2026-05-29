use std::path::Path;
use std::process::Command;

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct MediaProbeResult {
    pub duration: f64,
    pub width: u32,
    pub height: u32,
    pub fps: f64,
    pub video_codec: Option<String>,
    pub audio_codec: Option<String>,
    pub sample_rate: Option<u32>,
    pub channels: Option<u32>,
    pub bitrate: u64,
    pub has_video: bool,
    pub has_audio: bool,
}

#[derive(Debug, Deserialize)]
struct FFprobeOutput {
    streams: Vec<FFprobeStream>,
    format: FFprobeFormat,
}

#[derive(Debug, Deserialize)]
struct FFprobeStream {
    codec_type: Option<String>,
    codec_name: Option<String>,
    width: Option<u32>,
    height: Option<u32>,
    r_frame_rate: Option<String>,
    avg_frame_rate: Option<String>,
    sample_rate: Option<String>,
    channels: Option<u32>,
    duration: Option<String>,
}

#[derive(Debug, Deserialize)]
struct FFprobeFormat {
    duration: Option<String>,
    bit_rate: Option<String>,
}

pub fn probe_media(path: &str, ffprobe_bin: &str) -> Result<MediaProbeResult> {
    let output = Command::new(ffprobe_bin)
        .args([
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            path,
        ])
        .output()
        .context("Failed to run ffprobe — is it installed and in PATH?")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(anyhow!("ffprobe failed: {}", stderr));
    }

    let probe: FFprobeOutput =
        serde_json::from_slice(&output.stdout).context("Failed to parse ffprobe output")?;

    let mut result = MediaProbeResult::default();

    if let Some(dur_str) = &probe.format.duration {
        result.duration = dur_str.parse().unwrap_or(0.0);
    }

    if let Some(br_str) = &probe.format.bit_rate {
        result.bitrate = br_str.parse::<u64>().unwrap_or(0) / 1000;
    }

    for stream in &probe.streams {
        match stream.codec_type.as_deref() {
            Some("video") if !result.has_video => {
                result.has_video = true;
                result.video_codec = stream.codec_name.clone();
                result.width = stream.width.unwrap_or(0);
                result.height = stream.height.unwrap_or(0);

                let fps_str = stream
                    .avg_frame_rate
                    .as_deref()
                    .or(stream.r_frame_rate.as_deref())
                    .unwrap_or("30/1");
                result.fps = parse_fraction(fps_str).unwrap_or(30.0);

                if result.duration == 0.0 {
                    if let Some(dur_str) = &stream.duration {
                        result.duration = dur_str.parse().unwrap_or(0.0);
                    }
                }
            }
            Some("audio") if !result.has_audio => {
                result.has_audio = true;
                result.audio_codec = stream.codec_name.clone();
                result.sample_rate = stream
                    .sample_rate
                    .as_ref()
                    .and_then(|s| s.parse().ok());
                result.channels = stream.channels;

                if result.duration == 0.0 {
                    if let Some(dur_str) = &stream.duration {
                        result.duration = dur_str.parse().unwrap_or(0.0);
                    }
                }
            }
            _ => {}
        }
    }

    Ok(result)
}

fn parse_fraction(s: &str) -> Option<f64> {
    let parts: Vec<f64> = s.split('/').filter_map(|p| p.parse().ok()).collect();
    match parts.as_slice() {
        [num, den] if *den != 0.0 => Some(num / den),
        [num] => Some(*num),
        _ => None,
    }
}

pub fn generate_thumbnail(
    media_path: &str,
    output_path: &str,
    time_seconds: f64,
    width: u32,
    ffmpeg_bin: &str,
) -> Result<()> {
    if let Some(parent) = Path::new(output_path).parent() {
        std::fs::create_dir_all(parent)?;
    }

    let time_str = format!("{:.3}", time_seconds);
    let scale_filter = format!("scale={}:-2", width);

    let output = Command::new(ffmpeg_bin)
        .args([
            "-ss",
            &time_str,
            "-i",
            media_path,
            "-frames:v",
            "1",
            "-vf",
            &scale_filter,
            "-q:v",
            "5",
            "-y",
            output_path,
        ])
        .output()
        .context("Failed to run ffmpeg for thumbnail")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(anyhow!("ffmpeg thumbnail failed: {}", stderr));
    }

    Ok(())
}

pub fn export_timeline(
    input_path: &str,
    output_path: &str,
    video_codec: &str,
    audio_codec: &str,
    width: u32,
    height: u32,
    frame_rate: f64,
    video_bitrate: u64,
    audio_bitrate: u64,
    crf: u32,
    extra_args: &[String],
    ffmpeg_bin: &str,
    progress_callback: impl Fn(f64) + Send + 'static,
) -> Result<()> {
    let scale_filter = format!("scale={}:{}", width, height);
    let fps_str = format!("{}", frame_rate);
    let crf_str = crf.to_string();
    let video_br = format!("{}k", video_bitrate);
    let audio_br = format!("{}k", audio_bitrate);

    let mut args = vec![
        "-i",
        input_path,
        "-vf",
        &scale_filter,
        "-r",
        &fps_str,
        "-c:v",
        video_codec,
        "-crf",
        &crf_str,
        "-maxrate",
        &video_br,
        "-bufsize",
        "2M",
        "-c:a",
        audio_codec,
        "-b:a",
        &audio_br,
        "-y",
        output_path,
    ];

    let extra: Vec<&str> = extra_args.iter().map(|s| s.as_str()).collect();
    args.extend_from_slice(&extra);

    let status = Command::new(ffmpeg_bin).args(&args).status()?;

    if !status.success() {
        return Err(anyhow!("FFmpeg export failed with status: {}", status));
    }

    if !Path::new(output_path).exists() {
        return Err(anyhow!(
            "FFmpeg reported success but output file is missing: {}",
            output_path
        ));
    }

    progress_callback(100.0);
    Ok(())
}
