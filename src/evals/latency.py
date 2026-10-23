"""Exact empirical percentiles from local spans, without averaging percentiles."""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

MIN_TAIL_SAMPLES = 1000  # Alice evaluation policy; not a number mandated by ISO.
BUDGETS = {"fast_local": (0.300, 0.500), "browser_media": (0.300, 0.500),
           "iot": (0.300, 0.500), "voice": (1.000, 1.500)}


def percentile(values, q):
    """Nearest rank: empirical inverse CDF, x[ceil(q*n)-1]. Unit: seconds."""
    if not 0 < q <= 1:
        raise ValueError("Percentile must be in (0, 1]")
    if not values:
        return None
    if any(not math.isfinite(x) or x < 0 for x in values):
        raise ValueError("Duration must be finite and non-negative")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def summarize(run_directory):
    directory = Path(run_directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (directory / "spans.jsonl").read_text(encoding="utf-8").splitlines() if line]
    if len({row["span_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate spans")
    complete = bool(manifest.get("complete")) and len(rows) == manifest.get("written")
    groups = defaultdict(list)
    for row in rows:
        attrs = row["attributes"]
        group = tuple(attrs.get("alice." + k, "unknown") for k in ("channel", "phase", "scenario", "cache", "mode", "backend"))
        groups[group].append((row["duration_s"], attrs.get("alice.outcome", "unknown")))
        if attrs.get("alice.phase") == "turn":
            events = {e["name"]: e["attributes"]["alice.offset.s"] for e in row.get("events", [])}
            # Paired, same monotonic clock, same turn. Never fill missing landmarks
            # with zero or infer real audio from a TTS function returning.
            for phase, first, last in (("input_to_response", "input_ready", "response_ready"),
                                       ("input_to_verified", "input_ready", "effect_verified"),
                                       ("input_to_node_result", "input_ready", "node_result_observed"),
                                       ("vad_to_playback_proxy", "vad_end_proxy", "playback_requested"),
                                       ("vad_to_tts_driver_proxy", "vad_end_proxy", "tts_driver_started")):
                if first in events and last in events and events[last] >= events[first]:
                    groups[(group[0], phase, *group[2:])].append((events[last] - events[first], attrs.get("alice.outcome", "unknown")))
    summaries = []
    for key, samples in sorted(groups.items()):
        channel, phase, scenario, cache, mode, backend = key
        values = [x[0] for x in samples]
        counts = Counter(x[1] for x in samples)
        p50, p95, p99 = [percentile(values, q) for q in (0.50, 0.95, 0.99)]
        budget = BUDGETS.get(channel)
        # Only the whole input-to-response boundary is an end-to-end gate.
        eligible = phase == "input_to_response" and mode == "runtime" and budget is not None
        gate = "not_applicable_stage_or_offline"
        if eligible:
            gate = "insufficient_samples" if len(values) < MIN_TAIL_SAMPLES else "within_observed_budget"
            if p95 >= budget[0] or p99 >= budget[1]:
                gate = "observed_budget_violation"
        if not complete:
            gate = "invalid_incomplete_export"
        summaries.append({"channel": channel, "phase": phase, "scenario": scenario, "cache": cache,
                          "mode": mode, "backend": backend, "n": len(values), "mean_s": sum(values) / len(values),
                          "p50_s": p50, "p95_s": p95, "p99_s": p99, "max_s": max(values),
                          "outcomes": dict(counts), "gate": gate,
                          "p99_evidence": "invalid_incomplete_export" if not complete else "descriptive_only" if len(values) < MIN_TAIL_SAMPLES else "empirical_tail",
                          "over_500ms": sum(v >= .5 for v in values),
                          "over_1500ms": sum(v >= 1.5 for v in values)})
    metadata = manifest.get("metadata", {})
    observer_file = directory / "observer_samples.json"
    if observer_file.is_file():
        observer = json.loads(observer_file.read_text(encoding="utf-8"))
        metadata["observer_total_call_s"] = {k: {"n": len(v), "p50": percentile(v,.5), "p95": percentile(v,.95), "p99": percentile(v,.99)} for k,v in observer.items()}
        metadata["observer_raw_samples_file"] = "observer_samples.json"
    return {"schema": 1, "run_id": manifest["run_id"], "complete": complete,
            "percentile_method": "empirical_inverse_cdf_nearest_rank", "unit": "s",
            "minimum_tail_samples_policy": MIN_TAIL_SAMPLES,
            "groups": summaries, "metadata": metadata}


def markdown(report):
    lines = ["# Baseline độ trễ Alice", "", "Đơn vị bảng: ms. Percentile: nearest rank từ mẫu thô; không gộp percentile của nhiều lần chạy.", "",
             f"Run: `{report['run_id']}`. Export đầy đủ: **{report['complete']}**.", "",
             "| Kênh | Giai đoạn | Kịch bản / cache / chế độ / backend | n | P50 | P95 | P99 | Đánh giá |",
             "|---|---|---|---:|---:|---:|---:|---|"]
    for group in report["groups"]:
        lines.append("| {channel} | {phase} | {scenario} / {cache} / {mode} / {backend} | {n} | {p50:.3f} | {p95:.3f} | {p99:.3f} | {gate} |".format(
            **group, p50=group["p50_s"] * 1000, p95=group["p95_s"] * 1000, p99=group["p99_s"] * 1000))
    lines.extend(["", "`returned` chỉ xác nhận hàm trả về; không chứng minh mục tiêu đã hoàn tất. Lỗi/timeout vẫn có thời gian chờ trong thống kê, với outcome riêng.", "",
                  "Offline/matcher, nhánh thiếu dependency, probe chỉ đọc và LLM call cô lập không được dùng để tuyên bố các kênh thực tế đạt SLO. Mốc VAD/playback/driver là proxy phần mềm, không phải thời điểm âm thanh thực sự tới tai người dùng.", "",
                  "Dưới 1,000 mẫu mỗi nhóm: P99 chỉ mô tả mẫu đã đo. Đủ mẫu cũng chưa phải chứng nhận ISO hoặc bằng chứng đại diện cho mọi tải/cấu hình.", "",
                  "## Metadata và phần chưa đo", "", "```json", json.dumps(report["metadata"], ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def write_report(directory):
    report = summarize(directory)
    path = Path(directory)
    (path / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (path / "report.md").write_text(markdown(report), encoding="utf-8")
    return report
