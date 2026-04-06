# 接口契约

检查编排主链只使用以下五类接口：

- `POST /api/v1/check-requests:candidates`
- `POST /api/v1/check-requests`
- `GET /api/v1/check-requests/{request_id}`
- `GET /api/v1/check-requests/{request_id}/result`
- `POST /api/v1/check-requests/{request_id}:publish`

说明：

- 以上接口统一按 `setup-and-auth.md` 的 PAT 规则调用。
