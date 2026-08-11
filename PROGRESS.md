# Tiến độ lab

Theo dõi những gì đã làm cho từng checkpoint trong [CHECKPOINTS.md](CHECKPOINTS.md). Cập nhật dần khi hoàn thành thêm việc.

## Checkpoint 0 — Setup và baseline

**Trạng thái: Hoàn tất**

- Tạo `.env` từ `.env.example` (Langfuse key đang để trống, chưa điền).
- Chạy API (`uvicorn app.main:app --env-file .env`), `/health` trả `ok: true`.
- Chạy `python scripts/load_test.py`, sinh `data/logs.jsonl` (20 dòng, sau khi xoá file cũ để đo sạch).
- Chạy `python scripts/validate_logs.py` lấy baseline: **30/100** (đã lưu vào `submission/REPORT.md` mục 2).
  - 20/20 record thiếu required fields (100%).
  - 20/20 record thiếu enrichment (100%).
  - 0 correlation ID unique.
- Ghi nhận: 2026-08-11.

## Checkpoint 1 — Logging và PII

**Trạng thái: Hoàn tất (kỹ thuật) — cần tự bổ sung evidence/screenshot**

- [x] `app/middleware.py`: extract `x-request-id` từ header hoặc generate `req-<8-char-hex>`, bind correlation_id vào structlog contextvars, `clear_contextvars()` đầu mỗi request, gắn `x-request-id` + `x-response-time-ms` vào response headers.
- [x] `app/main.py`: enrich log với `user_id_hash`, `session_id`, `feature`, `model`, `env` qua `bind_contextvars`.
- [x] `app/logging_config.py`: đăng ký `scrub_event` processor (chạy trước khi ghi file).
- [x] `app/pii.py`: thêm pattern `passport` và `address_vn`.
- [x] `validate_logs.py`: **100/100** (0 missing required, 0 missing enrichment, 10 unique correlation ID, 0 PII leak). Ghi nhận 2026-08-11.
- [x] `python -m pytest -q`: 22 passed.
- [ ] **Còn thiếu (bạn tự làm):** chụp ảnh log có correlation ID, ảnh PII đã redact, lưu vào `submission/evidence/` theo yêu cầu Checkpoint 1 trong CHECKPOINTS.md.

## Checkpoint 2 — Metrics, traces và dashboard

**Trạng thái: Hoàn tất**

Đã làm (code):
- [x] `config/alert_rules.yaml`: điền 3 alert (`high_latency_p95`, `elevated_error_rate`, `quality_score_drop`), map theo `config/slo.yaml`.
- [x] `docs/alerts.md`: điền runbook chi tiết cho 3 alert (severity, điều kiện, 3 bước kiểm tra, mitigation, owner).
- [x] `scripts/dashboard.py`: dashboard Streamlit mới, đọc `data/logs.jsonl` + `config/dashboard.yaml` động (không hardcode số liệu/threshold), đủ 6 panel. Đã smoke-test chạy được (HTTP 200), chưa có evidence ảnh runtime.
- [x] `requirements.txt`: thêm `streamlit==1.39.0`, `pandas==2.2.3`. Đã cài vào `.venv`.
- [x] `python scripts/validate_dashboard.py` → `HỢP LỆ: 6/6 panel` (config này vốn đã hoàn chỉnh sẵn từ đầu, không phải TODO).

Đã làm (Langfuse):
- [x] Điền Langfuse key vào `.env`, restart `uvicorn`, xác nhận `tracing_enabled: true` qua `/health`.
- [x] Tạo prompt `day13-chat` v1 (label `baseline`+`production`) và v2 (label `candidate`).
- [x] Chạy `load_test.py` với `LANGFUSE_PROMPT_LABEL=baseline` và `candidate` (10 request/batch) → ≥10 traces có metadata trên Langfuse.
- [x] Mở 2 trace kiểm tra metadata — cả 2 đều `prompt_source=langfuse` (không phải local-fallback):
  - baseline: trace `a92287a50973ebb6e719f941284e3758`, `prompt_version=1`
  - candidate: trace `e116d1054e3dfa0c8c89fee9c1e9cada`, `prompt_version=2`
  - Evidence: `submission/evidence/trace_prompt_baseline_v1.png`, `trace_prompt_candidate_v2.png`

- [x] Đổi label `production` sang v2, sau đó rollback về v1 — chụp ảnh trước/sau (`prompt_label_after_switch_to_v2.png`, `prompt_rollback_to_v1.png`). Xác nhận `production` là label exclusive, tự chuyển giữa các version.

- [x] Chạy dashboard Streamlit, chụp ảnh riêng 6 panel, lưu vào `submission/evidence/` (`latency_percentiles.PNG`, `request_traffic.PNG`, `error_rate_and_breakdown.PNG`, `cost_over_time.PNG`, `input_and_output_tokens.PNG`, `quality_proxy.PNG`). Tất cả đạt threshold theo `config/dashboard.yaml`: P95=983ms, error=0%, cost=$0.149, tokens=11968, quality=0.88.

**Checkpoint 2: Hoàn tất toàn bộ (code + Langfuse + dashboard + evidence).**

## Checkpoint 3 — Challenge chính thức

**Trạng thái: Hoàn tất** (`config/challenge.json`: `incident=rag_slow`, `affected_feature=refund`, `seed=1303`)

- [x] `python scripts/inject_incident.py` → bật `rag_slow`.
- [x] `python scripts/load_test.py --challenge --concurrency 5` → 5 query `feature=refund`, client đo latency 10.6s–13.3s (tăng dần).
- [x] Xác định triệu chứng từ metrics: dashboard Latency panel chỉ báo P95=2651ms (trong SLO, KHÔNG breach) — phát hiện gap giám sát vì không phản ánh đúng latency client thực đo.
- [x] Dùng trace khoanh vùng: 5 trace Langfuse đều Latency=2.65s, khớp server-side `latency_ms`, không khớp client latency → xác nhận độ trễ thật nằm ở tầng queueing/event loop, không phải trong span generation.
- [x] Dùng log chứng minh root cause: `data/logs.jsonl` cho thấy `request_received` của request sau chỉ xuất hiện sau `response_sent` của request trước → server xử lý tuần tự dù client gửi đồng thời.
- [x] Root cause 2 tầng: (1) `time.sleep(2.5)` trong `mock_rag.retrieve()` khi `rag_slow=True`; (2) `async def chat()` gọi hàm đồng bộ `agent.run()` trực tiếp, chặn event loop, khuếch đại latency ~5 lần dưới tải đồng thời.
- [x] Fix action + preventive measure đã viết vào `submission/REPORT.md` mục 6.
- [x] Đã tắt incident (`inject_incident.py --disable`) sau khi điều tra xong.
- Evidence: `incident_latency_spike.png`, `incident_trace_table.png`.

## Hoàn tất — Báo cáo và demo

**Trạng thái: Gần xong — chỉ còn phần bạn tự điền + tự commit**

- [x] Điền `submission/REPORT.md` mục 2, 3, 5, 6 (kỹ thuật) và mục 1 (tên nhóm, thành viên, repo URL).
- [x] `python -m pytest -q` → 22 passed.
- [x] Dọn scaffold thừa do `uv init` tự sinh (`main.py` gốc), vá `pyproject.toml`/`uv.lock` để `uv run` không còn lỗi khoá file.
- [x] Viết `EXPLANATION.md` — giải thích chi tiết từng phần + Q&A dự kiến, dùng để ôn trước khi demo/vấn đáp.
- [ ] **Bạn tự làm:** điền vai trò từng thành viên (mục 1) + bảng đóng góp cá nhân (mục 7) trong `submission/REPORT.md` — cần commit/PR thật của từng người, tôi không tự biết được.
- [ ] `git status --short` — kiểm tra lại không có secret/PII trước khi commit (xem danh sách file mới bên dưới).
- [ ] Commit (tự làm hoặc nhờ tôi commit sau khi mục 1/7 điền xong) → sau đó điền "Commit SHA cuối" vào mục 1 bằng `git log -1 --format=%H`.
- [ ] Chuẩn bị demo ngắn theo luồng Metrics → Traces → Logs → Root cause (đã có sẵn nội dung trong `EXPLANATION.md` mục 6).
