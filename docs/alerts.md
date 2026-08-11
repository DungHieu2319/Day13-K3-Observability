# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert 1

- Tên: high_latency_p95
- Severity: high
- SLI/SLO liên quan: `latency_p95_ms` (mục tiêu ≤ 3000ms, `config/slo.yaml`)
- Điều kiện và thời gian duy trì: P95 latency > 3000ms, duy trì liên tục 5 phút
- Ảnh hưởng tới người dùng: Trả lời chậm, có thể timeout ở client hoặc trải nghiệm chờ lâu
- Ba bước kiểm tra đầu tiên:
  1. Xem panel Latency trên dashboard để xác nhận feature/khoảng thời gian bị ảnh hưởng
  2. Mở trace chậm nhất trong khoảng đó trên Langfuse, xác định span nào (retrieval, LLM call...) chiếm phần lớn thời gian
  3. Dùng correlation ID của trace đó tra `data/logs.jsonl` để xem log chi tiết request
- Mitigation tạm thời: Bật rate limit hoặc giảm concurrency phía client, cân nhắc rollback prompt/tính năng vừa deploy nếu trùng thời điểm
- Owner: Dashboard, SLO & Alert

## Alert 2

- Tên: elevated_error_rate
- Severity: critical
- SLI/SLO liên quan: `error_rate_pct` (mục tiêu ≤ 2%, `config/slo.yaml`)
- Điều kiện và thời gian duy trì: Error rate > 2%, duy trì liên tục 5 phút
- Ảnh hưởng tới người dùng: Request bị lỗi (HTTP 500), không nhận được câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Xem panel Errors để biết `error_type` nào chiếm đa số
  2. Lọc log `event=request_failed` trong `data/logs.jsonl` theo `error_type` và `correlation_id`
  3. Kiểm tra trace tương ứng trên Langfuse để xác định span/tool nào raise exception
- Mitigation tạm thời: Rollback thay đổi gần nhất (prompt, config, deploy), hoặc tắt incident injection nếu đang test
- Owner: Dashboard, SLO & Alert

## Alert 3

- Tên: quality_score_drop
- Severity: medium
- SLI/SLO liên quan: `quality_score_avg` (mục tiêu ≥ 0.75, `config/slo.yaml`)
- Điều kiện và thời gian duy trì: `mean(quality_score)` < 0.75, duy trì liên tục 15 phút
- Ảnh hưởng tới người dùng: Câu trả lời kém liên quan hoặc kém chất lượng hơn bình thường, không nhất thiết báo lỗi HTTP
- Ba bước kiểm tra đầu tiên:
  1. Xem panel Quality để xác nhận xu hướng giảm và khoảng thời gian
  2. Kiểm tra `prompt_label`/`prompt_version` trong trace metadata xem có vừa đổi label không
  3. So sánh `answer_preview` trong log của các request điểm thấp với input tương ứng
- Mitigation tạm thời: Rollback `production` label về version prompt trước đó (xem [PROMPT_VERSIONING.md](PROMPT_VERSIONING.md))
- Owner: Dashboard, SLO & Alert
