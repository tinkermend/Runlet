# 接口契约

Skill 在检查编排主链只使用以下五类接口：

- `POST /api/v1/check-requests:candidates`
- `POST /api/v1/check-requests`
- `GET /api/v1/check-requests/{request_id}`
- `GET /api/v1/check-requests/{request_id}/result`
- `POST /api/v1/check-requests/{request_id}:publish`

说明：

- 以上接口统一按 `setup-and-auth.md` 的 PAT 规则调用。
- `:publish` 仅在本次检查执行成功后作为可选后置动作使用。
