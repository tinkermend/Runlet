# Runlet Console Frontend

React + Vite + TypeScript management console for the Runlet platform.

## Local Development

```bash
# Install dependencies
npm install

# Start dev server (proxies /api to localhost:8000)
npm run dev

# Run tests
npm test -- --run

# Production build
npm run build
```

## Pages

- `/login` — Console login
- `/dashboard` — Summary cards + recent exceptions
- `/tasks` — Task list with status and last run info
- `/tasks/new` — 3-step task creation wizard
- `/tasks/:id` — Task detail with recent runs
- `/assets` — Asset browser grouped by system → page
- `/assets/:id` — Asset detail with raw facts (collapsible)
- `/systems` — System list with onboarding status
- `/systems/new` — System onboarding form
- `/results` — Paginated run results

## Tech Stack

- React 18 + React Router v6
- TanStack Query v5
- Lucide React icons
- Vitest + Testing Library
