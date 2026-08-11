# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm: Gì Cũng Được
- Repository URL: https://github.com/DungHieu2319/Day13-K3-Observability
- Commit SHA cuối: [TODO: điền sau khi commit lần cuối — chạy `git log -1 --format=%H`]
- Thành viên và vai trò:
  | STT | Họ và Tên | Mã Học Viên | Vai trò |
  |---|---|---|---|
  | 1 | Nguyễn Tiến | 2A202601655 | Logging & PII |
  | 2 | Trần Tiến Dũng | 2A202601783 | Tracing & Prompt Version |
  | 3 | Lê Hoàng Việt | 2A202601543 | Dashboard, SLO & Alert |
  | 4 | Nguyễn Thiên Tài | 2A202601849 | Incident Report & Demo |

## 2. Kết quả kỹ thuật

- Baseline `validate_logs.py` (Checkpoint 0, trước khi hoàn thiện TODO): 30/100 — 20/20 record thiếu required fields, 20/20 thiếu enrichment, 0 correlation ID unique. Ghi nhận ngày 2026-08-11.
- Điểm `validate_logs.py`: 100/100 (2026-08-11, sau khi hoàn thiện TODO logging/PII)
- Tổng số traces: ~60 trace (Langfuse Tracing hiển thị Total ≈ 120 dòng = 60 root trace + 60 generation con, filter "Is Root Observation" True:60/False:60)
- Số PII leak còn lại: 0 (`validate_logs.py`: "Potential PII leaks detected: 0")
- Link/đường dẫn dashboard: chạy local, không public — `uv run streamlit run scripts/dashboard.py` → `http://localhost:8501` (nguồn dữ liệu `data/logs.jsonl`, contract `config/dashboard.yaml`)

## 3. Logging và tracing

- Evidence correlation ID: `submission/evidence/correlation_id.png` (nhiều request, mỗi request 1 `correlation_id` riêng, xuyên suốt `request_received`→`response_sent`)
- Evidence PII redaction: `submission/evidence/pii_redaction.png` (email, SĐT VN, thẻ tín dụng đều bị thay bằng `[REDACTED_*]` trong `message_preview`)
- Evidence trace waterfall: `submission/evidence/trace_prompt_baseline_v1.png` (root `run` chứa 1 span con `generation`, thời lượng khớp nhau vì generation chiếm gần hết thời gian xử lý)
- Giải thích một span đáng chú ý: span `generation` trong mỗi trace bọc toàn bộ `LabAgent.run()` — gồm cả bước retrieval (`mock_rag.retrieve`) lẫn gọi LLM giả lập, nên latency của span này là tổng 2 bước chứ không tách riêng. Điều này từng gây hiểu lầm ở Checkpoint 3: span chỉ báo 2.65s dù người dùng thực tế chờ tới 13.3s, vì thời gian bị "xếp hàng" chờ event loop rảnh không nằm trong span (xảy ra trước khi hàm `run()` được gọi) — bài học: đo latency ở lớp entrypoint/middleware hoặc client, không chỉ trong 1 span xử lý.

## 4. Prompt versioning

- Prompt name: `day13-chat`
- Version/label baseline: version 1, label `baseline` (đồng thời `production` lúc tạo)
- Version/label candidate: version 2, label `candidate`
- Trace ID của mỗi version: baseline → `a92287a50973ebb6e719f941284e3758` (prompt_version=1, prompt_source=langfuse); candidate → `e116d1054e3dfa0c8c89fee9c1e9cada` (prompt_version=2, prompt_source=langfuse). Ảnh: `submission/evidence/trace_prompt_baseline_v1.png`, `submission/evidence/trace_prompt_candidate_v2.png`.
- Bằng chứng đổi label hoặc rollback: đổi `production` từ v1 sang v2 (`submission/evidence/prompt_label_after_switch_to_v2.png`), sau đó rollback `production` về v1 (`submission/evidence/prompt_rollback_to_v1.png`)

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`: `HỢP LỆ: 6/6 panel` (2026-08-11)
- Evidence dashboard: `submission/evidence/latency_percentiles.PNG`, `request_traffic.PNG`, `error_rate_and_breakdown.PNG`, `cost_over_time.PNG`, `input_and_output_tokens.PNG`, `quality_proxy.PNG`. Kết quả: P95 latency=983ms, traffic=1.17 req/min (70 request), error rate=0%, cost=$0.149, tokens=11968, quality=0.88 — cả 6 đều đạt threshold.
- SLO đã chọn và lý do: theo `config/slo.yaml` — latency P95 ≤ 3000ms (target 99.5%), error rate ≤ 2% (target 99.0%), cost/ngày ≤ $2.5, quality trung bình ≥ 0.75 (target 95%). Ngưỡng latency/error dựa trên trải nghiệm chat thời gian thực (chờ quá 3s hoặc lỗi >2% đã ảnh hưởng rõ tới người dùng); ngưỡng cost/quality dùng làm rào cản ngân sách và chất lượng tối thiểu, không phải mục tiêu tối ưu prompt.
- Alert rules và runbook: 3 alert symptom-based trong `config/alert_rules.yaml` (`high_latency_p95`, `elevated_error_rate`, `quality_score_drop`), runbook chi tiết từng alert tại `docs/alerts.md`.

## 6. Điều tra challenge

- Challenge ID: `day13-k3-observability-v1` (cohort K3, incident `rag_slow`, affected_feature `refund`, seed 1303)
- Triệu chứng từ metrics: chạy `python scripts/inject_incident.py` + `python scripts/load_test.py --challenge --concurrency 5` với 5 query `feature=refund`. Client đo latency tăng dần theo thứ tự request và vượt xa bình thường: 10,645ms → 13,306ms → 13,304ms → 13,308ms → 13,308ms (bình thường ~150ms). Đáng chú ý: dashboard panel Latency (dựa trên `latency_ms` server tự log) chỉ báo P95=2651ms — **vẫn nằm trong SLO ≤3000ms, không breach** (evidence: `submission/evidence/incident_latency_spike.png`). Đây là một gap giám sát: metric nội bộ không phản ánh đúng latency người dùng thực sự chịu.
- Trace ID liên quan: 5 trace Langfuse của batch challenge (correlation_id `req-948952c4`, `req-838a9653`, `req-2a4a6a59`, `req-46772db2`, `req-e9826ecf`), tất cả đều có Latency=2.65s trên Langfuse (evidence: `submission/evidence/incident_trace_table.png`) — khớp với `latency_ms` server-side, không phải latency client thực đo.
- Log line/correlation ID liên quan: `data/logs.jsonl`, ví dụ `correlation_id=req-e9826ecf`, `latency_ms=2651`, `feature=refund`, `ts` các request `request_received` cách nhau đúng bằng khoảng `response_sent` của request trước — chứng minh server xử lý **tuần tự**, không song song, dù client gửi đồng thời (`concurrency=5`).
- Root cause: có 2 tầng.
  1. **Nguyên nhân trực tiếp (do incident):** `app/mock_rag.py` gọi `time.sleep(2.5)` trong `retrieve()` khi cờ `rag_slow=True`, mô phỏng vector store/retrieval chậm cho các query chứa từ khóa "refund".
  2. **Nguyên nhân khuếch đại (bug kiến trúc có thật):** `app/main.py` khai `async def chat(...)` nhưng gọi `agent.run()` (hàm đồng bộ, chứa `time.sleep`) trực tiếp mà không đưa vào threadpool (`run_in_threadpool`/`asyncio.to_thread`). `time.sleep` đồng bộ chặn toàn bộ event loop của asyncio, nên các request đồng thời bị xử lý tuần tự thay vì song song — request cuối phải chờ tất cả request trước giải phóng event loop, khiến latency thực tế người dùng chịu (~13.3s) gấp ~5 lần latency nội bộ mỗi request (~2.65s).
- Fix action:
  1. Ngắn hạn (khi incident xảy ra thật): thêm timeout cho bước retrieval, trả fallback answer nếu vector store không phản hồi kịp threshold; tắt/rollback incident nếu là do deploy gần đây.
  2. Dài hạn (fix bug khuếch đại): đổi `agent.run()` sang chạy trong threadpool (`await run_in_threadpool(agent.run, ...)`) hoặc chuyển các I/O chặn (`retrieve`, LLM call) sang async thật, để 1 request chậm không chặn các request khác.
- Preventive measure: thêm alert `high_latency_p95` (đã có trong `config/alert_rules.yaml`) nhưng cần bổ sung thêm alert/metric đo **latency đầu-cuối phía client hoặc tại load balancer/gateway** (không chỉ latency nội bộ server) để không bỏ sót các sự cố bị khuếch đại bởi nghẽn xử lý; đưa test tải với concurrency > 1 vào CI/staging để phát hiện sớm các bug block event loop trước khi lên production.

## 7. Đóng góp cá nhân

Với mỗi thành viên, ghi rõ nhiệm vụ và link commit/PR tương ứng.

| Thành viên | Phần việc | Commit/PR | Điều đã học |
|---|---|---|---|
| Nguyễn Tiến | Logging & PII: correlation ID + clear/bind contextvars (`app/middleware.py`), log enrichment `user_id_hash`/`session_id`/`feature`/`model`/`env` (`app/main.py`), pipeline redact PII trước khi ghi file (`app/logging_config.py`), thêm pattern passport/địa chỉ VN (`app/pii.py`) | `6535d08` | Cơ chế contextvars của structlog để propagate correlation ID xuyên request mà không truyền tay qua từng hàm; vì sao thứ tự processor (redact trước khi ghi file) quyết định dữ liệu có bị lộ hay không |
| Trần Tiến Dũng | Tracing & Prompt Version: cấu hình Langfuse key, tạo prompt `day13-chat` version 1 (`baseline`+`production`) và version 2 (`candidate`), chạy trace theo từng label, đổi label `production` sang v2 rồi rollback về v1 | `6535d08` | Phân biệt version (bất biến) và label (con trỏ có thể đổi) trong prompt management; rollback thực chất là đổi label chứ không sửa nội dung |
| Lê Hoàng Việt | Dashboard, SLO & Alert: dựng dashboard 6 panel (`scripts/dashboard.py`) đọc động từ `config/dashboard.yaml`, chọn threshold SLO (`config/slo.yaml`), viết 3 alert rule symptom-based (`config/alert_rules.yaml`) + runbook chi tiết (`docs/alerts.md`) | `6535d08` | Vì sao alert nên symptom-based thay vì cause-based; percentile (P95) phản ánh trải nghiệm người dùng tệ nhất tốt hơn giá trị trung bình |
| Nguyễn Thiên Tài | Incident Report & Demo: chạy challenge chính thức (`inject_incident.py`, `load_test.py --challenge`), điều tra root cause 2 tầng (RAG chậm do inject + bug block event loop khuếch đại latency), viết fix action/preventive measure | `6535d08` | Đọc metric nội bộ (P95, latency_ms) không đủ để đánh giá đúng trải nghiệm người dùng nếu có nghẽn xử lý phía trước; cách đối chiếu số liệu client vs server để phát hiện gap giám sát |

Ghi chú: cả nhóm làm chung 1 commit (`6535d08`, xem https://github.com/DungHieu2319/Day13-K3-Observability/commit/6535d08d7abae0da7faa68cc87312e020b8157f0) trong buổi lab, chưa tách commit riêng theo từng người.
