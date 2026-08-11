# Giải thích chi tiết — dùng để hiểu và trình bày khi demo/vấn đáp

Tài liệu này giải thích **vì sao** từng phần được làm như vậy, không chỉ **đã làm gì**. Rubric B1 (20 điểm) chấm khả năng trả lời câu hỏi về logging, tracing, prompt version, PII, percentile, alert — nên đọc kỹ phần Q&A ở cuối mỗi mục.

Không cần học thuộc — hiểu ý chính rồi tự diễn đạt lại bằng lời của mình sẽ tự nhiên hơn khi bị hỏi dồn.

---

## 1. Correlation ID & Logging ([app/middleware.py](app/middleware.py), [app/main.py](app/main.py))

### Đã làm gì
- Middleware `CorrelationIdMiddleware` chạy trước mọi request: lấy `x-request-id` từ header nếu client gửi sẵn (để nối chuỗi trace giữa nhiều service), nếu không có thì tự sinh `req-<8 hex>`.
- `bind_contextvars(correlation_id=...)` gắn ID này vào structlog contextvars — từ đó **mọi** dòng log phát sinh trong lúc xử lý request đó (dù gọi từ hàm nào, module nào) đều tự động có field `correlation_id` mà không cần truyền tay qua từng hàm.
- `clear_contextvars()` gọi **đầu tiên** trong mỗi request.

### Vì sao phải `clear_contextvars()` đầu mỗi request
Đây là câu hỏi rất hay bị hỏi. `contextvars` là cơ chế lưu biến theo **execution context** của Python (mỗi task async có context riêng), nhưng nếu không dọn thì dữ liệu bind từ request trước có thể vô tình còn sót và bị log lẫn vào request sau, đặc biệt khi framework tái sử dụng worker/thread. Clear trước, bind sau = đảm bảo mỗi request bắt đầu "sạch", không leak dữ liệu (kể cả correlation_id lẫn user_id_hash) giữa các user khác nhau.

### Vì sao enrichment (`user_id_hash`, `session_id`, `feature`, `model`, `env`) cũng dùng `bind_contextvars`
Cùng lý do: enrichment cần xuất hiện trên **cả 2** dòng log của 1 request (`request_received` và `response_sent`) mà không phải lặp lại tham số ở từng lời gọi `log.info(...)`. Bind 1 lần ở đầu handler `/chat`, mọi `log.info`/`log.error` phía sau tự thừa hưởng.

### Vì sao `user_id_hash` chứ không phải `user_id` thô
PII minimization: chỉ cần định danh user để truy vết (correlate) trong log, không cần biết user thật là ai từ log. `hash_user_id()` dùng SHA-256, lấy 12 ký tự đầu — đủ để phân biệt user nhưng không đảo ngược lại được user_id gốc.

### Q&A dự kiến
- *"Nếu 2 request tới cùng lúc, correlation_id có bị đè lên nhau không?"* → Không, vì contextvars cô lập theo từng task/coroutine của asyncio, mỗi request có 1 bản context riêng dù chạy "đồng thời" trên cùng process.
- *"Sao không dùng UUID đầy đủ cho correlation_id?"* → Dùng 8 hex đủ để tránh trùng trong phạm vi log của 1 lần chạy lab, ngắn hơn nên log/dashboard dễ đọc hơn; đây là quyết định đánh đổi entropy lấy tính dễ đọc, chấp nhận được vì không phải hệ thống production thật.

---

## 2. PII Redaction ([app/pii.py](app/pii.py), [app/logging_config.py](app/logging_config.py))

### Đã làm gì
- `PII_PATTERNS`: dict regex cho email, SĐT VN, CCCD, thẻ tín dụng, **passport**, **địa chỉ VN** (2 pattern mới tự thêm).
- `scrub_text()`: chạy tuần tự từng regex, thay match bằng `[REDACTED_<LOẠI>]`.
- `scrub_event` (processor structlog): áp `scrub_text` lên `event_dict["payload"]` và `event_dict["event"]` **trước khi** `JsonlFileProcessor` ghi ra file.

### Vì sao thứ tự processor trong `configure_logging()` quan trọng
```
merge_contextvars → add_log_level → TimeStamper → scrub_event → ... → JsonlFileProcessor → JSONRenderer
```
`scrub_event` phải đứng **trước** `JsonlFileProcessor` (bước ghi file). Nếu đặt sau, dữ liệu PII gốc đã bị ghi xuống đĩa trước khi được che — vô nghĩa. Đây là nguyên tắc chung: redact phải xảy ra ở điểm sớm nhất có thể trước khi dữ liệu "rời khỏi" vùng kiểm soát (ở đây là trước khi persist).

### Vì sao dùng regex thay vì LLM/NER để phát hiện PII
Regex: nhanh, deterministic (luôn cho cùng kết quả với cùng input), không tốn thêm chi phí gọi model, dễ audit (đọc pattern là biết chính xác nó bắt gì). Nhược điểm: cứng nhắc, dễ miss các dạng PII không theo format chuẩn (ví dụ tên riêng, địa chỉ viết tự do) — đây là lý do `validate_logs.py` chỉ kiểm tra được 4 loại PII cố định (email, phone, cccd, credit card), không đảm bảo 100% mọi loại PII đều bị bắt.

### Q&A dự kiến
- *"Regex có thể miss trường hợp nào?"* → Địa chỉ viết không theo pattern chuẩn, tên riêng, số điện thoại quốc tế không phải VN, PII trong ảnh/file đính kèm (ngoài phạm vi lab).
- *"Tại sao PII check trong `validate_logs.py` lại độc lập với `app/pii.py`?"* → Đúng, `scripts/validate_logs.py` tự định nghĩa lại `PII_DETECTORS` riêng — đây là chủ đích của đề bài: validator đóng vai "người ngoài" kiểm tra kết quả cuối, không tin tưởng mù quáng vào logic redact của chính app (giống nguyên tắc kiểm thử độc lập).

---

## 3. Prompt Versioning ([app/prompt_management.py](app/prompt_management.py))

### Khái niệm version vs label
- **Version**: mỗi lần sửa nội dung prompt và lưu = 1 version mới, đánh số tăng dần (1, 2, 3...), **không đổi được nội dung** version cũ (immutable).
- **Label**: một cái "tên bí danh" trỏ tới 1 version cụ thể tại 1 thời điểm — **có thể đổi** label sang trỏ version khác bất cứ lúc nào (đây chính là cơ chế rollback: đổi label `production` từ version 2 về version 1 = rollback, không cần sửa/xoá gì).
- App luôn đọc prompt qua `LANGFUSE_PROMPT_LABEL` (biến môi trường), nghĩa là **app không biết** đang chạy version mấy cho tới khi Langfuse trả về — tách rời code khỏi nội dung prompt.

### Cơ chế fallback
`resolve_prompt()` trong try/except: nếu gọi Langfuse lỗi (mất mạng, sai key, timeout) → dùng `DEFAULT_PROMPT_TEMPLATE` local, đánh dấu `prompt_source="local-fallback"`. Đây là pattern **graceful degradation**: app vẫn chạy được (không crash toàn bộ) dù dependency ngoài (Langfuse) chết, nhưng có đánh dấu rõ ràng trong trace để không "giả vờ" đã dùng managed prompt.

### Q&A dự kiến
- *"Label `production` đang trỏ version nào thì biết bằng cách nào?"* → Vào Langfuse UI, tab Prompts, xem badge label ngay cạnh version tương ứng.
- *"Nếu đổi label production nhưng server đang chạy không tự nhận ra?"* → Đúng — code cache prompt theo `cache_ttl_seconds=60` (xem `prompt_management.py`), nên tối đa 60s sau khi đổi label, request mới mới thấy version mới. Đây là đánh đổi giữa độ mới (freshness) và số lần gọi API Langfuse.

---

## 4. Dashboard ([scripts/dashboard.py](scripts/dashboard.py), [config/dashboard.yaml](config/dashboard.yaml))

### Vì sao `config/dashboard.yaml` là "contract"
File này định nghĩa chính xác: panel nào, field nào, phép tính gì (percentile/mean/sum), đơn vị gì, threshold bao nhiêu. `scripts/validate_dashboard.py` chỉ kiểm tra **cấu trúc** file này đúng schema — nó **không** biết dashboard thật trông ra sao. Vì vậy dù validator báo "6/6 panel hợp lệ", vẫn phải nộp ảnh chụp dashboard chạy thật — 2 thứ kiểm tra 2 lớp khác nhau (contract vs runtime).

### Vì sao dashboard đọc `data/logs.jsonl` thay vì gọi Langfuse
`data/logs.jsonl` là structured log app tự ghi — nguồn dữ liệu ổn định, đầy đủ field số (latency_ms, cost_usd, tokens...) để tính percentile/sum cục bộ, không phụ thuộc mạng hay rate-limit của Langfuse. Langfuse dùng cho mục đích khác: xem chi tiết từng trace/span để điều tra sâu, không phải nguồn tổng hợp số liệu cho dashboard operational.

### Vì sao P95 (không dùng trung bình) cho latency
Trung bình (mean) bị "che" bởi các request nhanh chiếm đa số — 1 request cực chậm giữa 99 request nhanh gần như không ảnh hưởng mean, nhưng vẫn là 1% user chịu trải nghiệm tệ. P95 trả lời câu hỏi thực tế hơn: "95% user tệ nhất trải nghiệm thế nào" — sát với SLO/SLA thực tế của ngành hơn trung bình.

### Q&A dự kiến
- *"Threshold P95 ≤ 3000ms tính từ đâu ra?"* → Là quyết định nghiệp vụ (business decision), không phải công thức toán — dựa trên UX: chat chờ quá 3 giây bắt đầu cảm thấy "chậm" rõ rệt với người dùng. Ghi trong `config/slo.yaml`.
- *"Sao Error rate panel không hiện gì khi không có lỗi?"* → Đúng thiết kế — code kiểm tra `if not failures.empty` mới vẽ chart phân loại lỗi, tránh vẽ chart rỗng gây rối mắt.

---

## 5. Alert Rules & SLO ([config/alert_rules.yaml](config/alert_rules.yaml), [docs/alerts.md](docs/alerts.md), [config/slo.yaml](config/slo.yaml))

### Symptom-based vs cause-based alert
Cả 3 alert (`high_latency_p95`, `elevated_error_rate`, `quality_score_drop`) đều **symptom-based**: dựa trên triệu chứng người dùng cảm nhận được (chậm, lỗi, trả lời tệ), không dựa trên nguyên nhân nội bộ (ví dụ "CPU > 80%", "vector store restart"). Lý do: triệu chứng phản ánh đúng impact thực tế và ổn định hơn — hệ thống có thể đổi kiến trúc nội bộ (đổi vector store, đổi model) nhưng alert vẫn còn ý nghĩa vì vẫn đo đúng cái người dùng quan tâm.

### Vì sao mỗi alert có "Ba bước kiểm tra đầu tiên" theo đúng thứ tự Dashboard → Trace → Log
Đây chính là luồng điều tra chuẩn của lab: **Metrics phát hiện** (dashboard báo threshold breach) → **Trace khoanh vùng** (span nào chậm/lỗi) → **Log chứng minh root cause** (chi tiết field nào, giá trị nào). Alert runbook được viết theo đúng luồng này để bất kỳ ai on-call cũng theo được quy trình nhất quán.

### Q&A dự kiến
- *"Vì sao quality_score_drop lại là alert riêng, không gộp vào error rate?"* → Vì 2 loại lỗi khác nhau: error rate là lỗi kỹ thuật (HTTP 500, exception), quality score là câu trả lời **vẫn thành công về mặt kỹ thuật** nhưng nội dung kém — 2 vấn đề cần người xử lý khác nhau (dev backend vs người phụ trách prompt).

---

## 6. Điều tra Challenge (Checkpoint 3) — phần quan trọng nhất để hiểu sâu

### Luồng điều tra đã làm
1. **Metrics**: chạy challenge (`rag_slow`, feature `refund`), quan sát 2 con số khác nhau:
   - Client (`load_test.py` tự đo bằng đồng hồ riêng): latency tăng dần 10.6s → 13.3s.
   - Server/dashboard (`latency_ms` app tự log): ổn định ~2.65s, **vẫn trong SLO** (≤3000ms).
2. **Trace**: mở Langfuse, span `generation` của cả 5 request đều báo đúng ~2.65s — khớp với server, **không khớp** với client.
3. **Log**: so `ts` giữa các dòng `request_received`/`response_sent` liên tiếp → thấy request sau chỉ bắt đầu xử lý ngay khi request trước xong, dù client gửi đồng thời (`concurrency=5`) → bằng chứng server xử lý **tuần tự**.

### Root cause 2 tầng — đây là điểm khác biệt của investigation này
1. **Tầng inject (chủ đích của đề)**: `mock_rag.py` có `time.sleep(2.5)` khi `rag_slow=True`.
2. **Tầng thật (bug kiến trúc, tự phát hiện thêm)**: `main.py` khai `async def chat(...)` nhưng gọi thẳng `agent.run()` (hàm đồng bộ chứa `time.sleep`) mà không đưa vào thread pool. `time.sleep` là **blocking call** — nó chặn cứng thread đang chạy event loop của asyncio. Vì uvicorn (mặc định) chạy 1 event loop trên 1 worker, mọi request khác (dù là request hoàn toàn không liên quan) đều phải **chờ** cho tới khi lệnh `sleep` hiện tại kết thúc mới được xử lý tiếp — kể cả việc đơn giản như trả response cho 1 request đã xử lý xong cũng bị treo.

### Bài học giám sát (insight quan trọng nhất, nên nói khi demo)
Metric nội bộ (đo bên trong hàm xử lý) có thể **"nói dối" một cách vô tình** — nó chỉ đo từ lúc code bắt đầu chạy, không đo thời gian chờ trước đó. Muốn biết đúng trải nghiệm người dùng, phải đo ở lớp gần người dùng nhất có thể (client, load balancer, gateway/edge) chứ không chỉ tin vào con số app tự báo cáo. Đây là lý do phần "Preventive measure" đề xuất thêm metric latency đo ở tầng client/gateway, không chỉ dựa vào `latency_ms` app tự log.

### Q&A dự kiến (khả năng cao sẽ bị hỏi)
- *"Tại sao dashboard không phát hiện được incident nghiêm trọng như vậy?"* → Vì dashboard dùng đúng con số app tự báo cáo (`latency_ms`), mà con số đó không tính thời gian request bị "xếp hàng" chờ do bug block event loop — dashboard không sai kỹ thuật, nhưng có blind spot.
- *"Cách fix bug block event loop?"* → Bọc lời gọi đồng bộ trong threadpool: `await run_in_threadpool(agent.run, ...)`, hoặc viết lại `retrieve()`/LLM call thành `async def` thật và dùng `await asyncio.sleep()`/HTTP client async thay vì `time.sleep()`/HTTP client đồng bộ.
- *"Sao P95 vẫn OK mà thực tế người dùng vẫn khổ?"* → Vì P95 tính trên latency_ms nội bộ (chỉ 5 mẫu, đều ~2.65s → P95 cũng ~2.65s), con số này che mất phần "chờ hàng" — minh hoạ rất rõ rằng threshold đúng công thức không đồng nghĩa hệ thống thực sự khoẻ.

---

## 7. Bản đồ file nhanh (tra cứu lúc demo)

| Việc | File |
|---|---|
| Correlation ID, response headers | `app/middleware.py` |
| Log enrichment, endpoint `/chat` | `app/main.py` |
| PII regex + hash user_id | `app/pii.py` |
| Cấu hình pipeline log (thứ tự processor) | `app/logging_config.py` |
| Lấy prompt theo label, fallback local | `app/prompt_management.py` |
| Giả lập RAG chậm/lỗi (nơi inject incident) | `app/mock_rag.py` |
| Cờ bật/tắt incident | `app/incidents.py` |
| Đọc & validate `config/challenge.json` | `app/challenge.py` |
| Dashboard Streamlit (6 panel) | `scripts/dashboard.py` |
| Contract 6 panel | `config/dashboard.yaml` |
| SLO threshold | `config/slo.yaml` |
| 3 alert rule | `config/alert_rules.yaml` |
| Runbook chi tiết từng alert | `docs/alerts.md` |
| Kiểm tra log baseline/sau khi sửa | `scripts/validate_logs.py` |
| Kiểm tra contract dashboard | `scripts/validate_dashboard.py` |
| Bật/tắt incident, chạy challenge | `scripts/inject_incident.py`, `scripts/load_test.py` |
