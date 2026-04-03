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

export interface TaskItem {
  id: number;
  name: string;
  system_name: string;
  status: string; // running / idle / failed / disabled
  last_run_at: string | null;
  last_run_status: string | null;
  schedule_preset: string;
}

export interface TaskDetail {
  id: number;
  name: string;
  system_name: string;
  status: string;
  schedule_preset: string;
  check_types: string[];
  recent_runs: RunResultItem[];
}

export interface WizardOptions {
  systems: SystemItem[];
  check_types: string[];
}

export interface AssetItem {
  id: number;
  check_type_label: string;
  version: string;
  status: string;
}

export interface PageGroup {
  page_name: string;
  assets: AssetItem[];
}

export interface SystemAssetGroup {
  system_id: number;
  system_name: string;
  pages: PageGroup[];
}

export interface AssetDetail {
  id: number;
  page_name: string;
  system_name: string;
  check_type_label: string;
  version: string;
  status: string;
  collected_at: string | null;
  raw_facts: Record<string, unknown> | null;
}
