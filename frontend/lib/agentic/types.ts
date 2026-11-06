export type Health = {
  status: string;
  service: string;
  environment: string;
  runtime: string;
  llm_provider: string;
  checks: { database: string; contracts: number };
};

export type ServiceInfo = {
  service: string;
  title: string;
  version: string;
  operations: number;
  servers?: string[];
  auth_required_operations?: number;
};

export type ModelInfo = {
  service: string;
  version: string;
  approved: boolean;
};

export type RunSummary = {
  executed?: number;
  passed?: number;
  failed?: number;
  blocked?: number;
  needs_review?: number;
  max_scenarios?: number;
  error?: string;
};

export type RunRecord = {
  run_id: string;
  service: string;
  status: string;
  target_url: string;
  tenant: string;
  model_version: string;
  correlation_id: string;
  summary: RunSummary | null;
  created_at: string | null;
};

export type RunPage = {
  items: RunRecord[];
  total: number;
  limit: number;
  offset: number;
};

export type Invariant = {
  name: string;
  passed: boolean;
  detail?: string;
  severity?: string;
};

export type ExecutionResult = {
  execution_id: string;
  test_id: string;
  status: string;
  failure_class: string;
  http_status: number | null;
  latency_ms: number | null;
  correlation_id: string;
  invariants: Invariant[];
  error: string | null;
};

export type Scenario = {
  test_id: string;
  service_name: string;
  endpoint: string;
  method: string;
  objective: string;
  expected_invariants: string[];
  expected_status: number;
  priority: string;
  requirement_ref: string;
  technique: string;
  tenant: string;
  model_version: string;
  execution_status?: string;
};

export type Metric = {
  available: boolean;
  value: number | null;
  detail: string;
  unit: string | null;
};

export type Report = {
  run_id: string;
  service?: string;
  correlation_id?: string;
  totals: Record<string, number>;
  api_coverage?: {
    operations_total: number;
    operations_exercised: number;
    percent: number;
    exercised: string[];
  };
  parameter_coverage?: { pairs_total?: number; pairs_covered?: number; percent?: number };
  model_quality?: Record<string, Metric>;
  tenant_isolation?: { passed: number; failed: number };
  latency_ms?: { count: number; min: number | null; max: number | null; avg: number | null; p50: number | null };
  defects?: Array<{
    test_id: string;
    endpoint: string;
    failure_class: string;
    failed_invariants: string[];
    http_status: number | null;
  }>;
  investigations?: Array<{
    test_id?: string;
    classification?: string;
    summary?: string;
    recommended_action?: string;
    llm_note?: string | null;
  }>;
  recommendations?: string[];
  llm?: { provider?: string; ok?: boolean };
};
