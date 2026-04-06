# 初始化与认证

- 启动前必须检查 `RUNLET_PAT`。
- 可选读取 `RUNLET_BASE_URL`，未设置时按编排器约定默认地址处理。
- 若 `RUNLET_PAT` 缺失时立即停止，并提示先去 Web 管理台创建 PAT（仅支持 3/7 天）。
- 所有 `/api/v1/check-requests*` 调用统一携带请求头：`Authorization: Bearer ${RUNLET_PAT}`。
