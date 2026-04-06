# 接口契约

检查编排主链只使用以下五类接口：

- `POST /api/v1/check-requests:candidates`
- `POST /api/v1/check-requests`
- `GET /api/v1/check-requests/{request_id}`
- `GET /api/v1/check-requests/{request_id}/result`
- `POST /api/v1/check-requests/{request_id}:publish`

说明：

- 以上接口统一按 `setup-and-auth.md` 的 PAT 规则调用。
- `GET /api/v1/check-requests/{request_id}` 返回的是队列态；对话轮询时仅用于判断是否继续等待。
- 对话层应将 `accepted`、`queued`、`running` 视为进行中，将 `completed`、`failed`、`retryable_failed`、`skipped` 视为终态。
- 一旦命中终态，必须转查 `GET /api/v1/check-requests/{request_id}/result`；最终“通过/失败”以 `execution_summary.status` 为准，而不是以状态接口的 `completed` 文案直接下结论。
