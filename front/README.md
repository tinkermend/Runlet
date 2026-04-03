# Runlet Console

前端管理控制台，基于 React + Vite + TypeScript 构建。

## 本地开发

```bash
cd front
npm install
npm run dev
```

访问 http://localhost:5173

## 测试

```bash
npm test -- --run
```

## 构建

```bash
npm run build
```

## 技术栈

- React 18 + TypeScript
- Vite 5
- React Router v6
- TanStack Query v5
- Lucide React (图标)
- Vitest + Testing Library (测试)

## 目录结构

```
src/
  app/
    providers/      # React context providers
    routes/         # 路由守卫组件
    app-shell.tsx   # 主布局（侧边栏 + 内容区）
    router.tsx      # 路由配置
  test/
    setup.ts        # 测试环境初始化
  main.tsx          # 应用入口
```
