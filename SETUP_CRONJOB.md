# Hướng dẫn Setup Lịch Tự Động Đáng Tin Cậy

## Vấn đề với GitHub Actions Scheduler

GitHub Actions `schedule` (cron) **không đáng tin cậy**:
- Chỉ là "best-effort" — GitHub không đảm bảo chạy đúng giờ
- Hay bị trễ từ vài phút đến vài giờ khi tải cao
- Có thể tự dừng sau khi workflow file bị sửa nhiều lần
- Tự vô hiệu hóa sau 60 ngày không có commit (xử lý bằng `keepalive.yml`)

**Giải pháp**: dùng `cron-job.org` (miễn phí) gọi thẳng GitHub API để trigger
`workflow_dispatch` — hoàn toàn tách biệt khỏi scheduler của GitHub.

---

## Bước 1: Tạo GitHub Personal Access Token

1. Vào https://github.com/settings/tokens → **Fine-grained tokens** → **Generate new token**
2. Đặt tên: `lotto535-cron-trigger`
3. **Repository access**: chọn `Only select repositories` → chọn repo `v5`
4. **Permissions**: `Actions` → **Read and write**
5. **Generate token** → Copy token (hiện 1 lần)

---

## Bước 2: Setup cron-job.org

1. Vào https://cron-job.org → Đăng ký miễn phí
2. **Dashboard** → **CREATE CRONJOB**

### Tạo Job 1 — Sau kỳ 13:00 (15:05 ICT = 08:05 UTC)

- **Title**: `Lotto 535 – Sau kỳ 13h`
- **URL**: 
```
https://api.github.com/repos/thuantn005/v5/actions/workflows/predict.yml/dispatches
```
- **Execution schedule**: `Every day` at `08:05 UTC` (= 15:05 giờ VN)
- **Request method**: `POST`
- **Request headers** (bấm "Advanced"):
  ```
  Authorization: Bearer <TOKEN_CỦA_BẠN>
  Accept: application/vnd.github+json
  Content-Type: application/json
  X-GitHub-Api-Version: 2022-11-28
  ```
- **Request body**:
  ```json
  {"ref": "main"}
  ```
- **Save**

### Tạo Job 2 — Sau kỳ 21:00 (23:05 ICT = 16:05 UTC)

Tương tự Job 1, chỉ đổi giờ thành `16:05 UTC` (= 23:05 giờ VN)

---

## Bước 3: Kiểm tra

Sau khi tạo, bấm **Run manually** trong cron-job.org → vào GitHub repo → tab
**Actions** → xem workflow `Lotto 5/35 Predict & Notify` có xuất hiện lần chạy mới
không (event sẽ hiển thị là `workflow_dispatch`).

---

## Tại sao cách này tốt hơn

| | GitHub cron | cron-job.org |
|---|---|---|
| Đúng giờ | Không đảm bảo | ✅ Rất chính xác |
| Dừng đột ngột | Có thể | Không |
| Phụ thuộc | GitHub scheduler | Server độc lập |
| Chi phí | Miễn phí | Miễn phí |
| Setup | Có sẵn | 5 phút |

---

## Lưu ý bảo mật

- Token chỉ cấp quyền `Actions: Read and write` trên **đúng repo v5**, không có
  quyền gì khác
- cron-job.org lưu header (có token) — nếu lo ngại, có thể dùng GitHub Secrets
  và tạo thêm 1 workflow `trigger.yml` nhận POST không xác thực, sau đó trigger
  `predict.yml` nội bộ (nhưng cách đơn giản trên là đủ cho repo cá nhân)
- Nên revoke và tạo token mới định kỳ (6 tháng/lần)
