export interface DashboardSummary {
  today_runs: number;
  active_tasks: number;
  systems_count: number;
  recent_failures_24h: number;
  recent_exceptions: RecentException[];
}

export interface RecentException {
  task_name: string;
  system_name: string;
  status: string;
  created_at: string;
}

export interface SystemItem {
  id: number;
  name: string;
  base_url: string;
  status: string; // ready / onboarding / failed
  task_count: number;
}

export interface RunResultItem {
  id: number;
  task_name: string;
  system_name: string;
  status: string;
  duration_ms: number | null;
  created_at: string;
}

export interface PaginatedResults {
  items: RunResultItem[];
  total: number;
  page: number;
  page_size: number;
}
