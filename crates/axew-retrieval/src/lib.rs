use pyo3::prelude::*;

#[pyfunction]
fn compute_temporal_iou(
    pred_start: f64,
    pred_end: f64,
    gt_start: f64,
    gt_end: f64,
) -> f64 {
    let intersection = (pred_end.min(gt_end) - pred_start.max(gt_start)).max(0.0);
    let union = (pred_end - pred_start) + (gt_end - gt_start) - intersection;
    if union == 0.0 {
        0.0
    } else {
        intersection / union
    }
}

#[pyfunction]
fn merge_overlapping_windows(windows: Vec<(f64, f64, f64)>) -> Vec<(f64, f64, f64)> {
    if windows.is_empty() {
        return vec![];
    }

    let mut sorted = windows;
    sorted.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());

    let mut merged = vec![sorted[0]];
    for (start, end, score) in sorted.into_iter().skip(1) {
        let last = merged.len() - 1;
        let (ps, pe, pscore) = merged[last];
        let overlap = (pe.min(end) - ps.max(start)).max(0.0);
        let span = (pe - ps).min(end - start);
        if span > 0.0 && overlap / span > 0.5 {
            merged[last] = (ps, pe.max(end), pscore.max(score));
        } else {
            merged.push((start, end, score));
        }
    }
    merged
}

#[pymodule]
fn axew_retrieval(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_temporal_iou, m)?)?;
    m.add_function(wrap_pyfunction!(merge_overlapping_windows, m)?)?;
    Ok(())
}
