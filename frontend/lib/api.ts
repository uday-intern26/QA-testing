export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type StatusName = "PASS" | "WARNING" | "FAIL" | "NOT_RUN" | "RUNNING" | "WAITING" | "SKIPPED" | string;

export interface ApplicationRecord {
  id: string;
  name: string;
  type: "web" | "desktop" | "video";
  url: string | null;
  executable_path: string | null;
  video_path: string | null;
  anchor_file: string | null;
  username: string | null;
  username_selector: string | null;
  password_selector: string | null;
  submit_selector: string | null;
  ready_selector: string | null;
  last_validation_status: string | null;
  last_validation_message: string | null;
  validation_screenshot: string | null;
}

export interface CatalogCategory {
  category: string;
  items: string[];
}

export interface CatalogResult {
  url: string;
  categories: CatalogCategory[];
  message: string;
}

export interface ValidationResult {
  status: "success" | "failed";
  reachable: boolean;
  login_successful: boolean;
  application_loaded: boolean;
  message: string;
  checks: { name: string; ok: boolean; detail: string }[];
  screenshot_url: string | null;
  application_id: string | null;
  jewelry: string[];
  catalog?: CatalogCategory[];
}

export interface ReferenceRecord {
  id: string;
  filename: string;
  width: number;
  height: number;
  side: string | null;
  earlobe_x: number | null;
  earlobe_y: number | null;
  earring_x: number | null;
  earring_y: number | null;
  ear_width: number | null;
  ear_height: number | null;
  vector_dx: number | null;
  vector_dy: number | null;
  normalized_distance: number | null;
  confidence: number | null;
  analysis_error: string | null;
  image_url: string;
}

export interface TestRecord {
  id: string;
  name: string;
  application_id: string;
  reference_id: string | null;
  jewelry_id: string | null;
  jewelry_type: string;
  ear_side: "left" | "right" | "both";
  selected_finger?: "thumb" | "index" | "middle" | "ring" | "little" | null;
  capture_fps: number;
  capture_duration_seconds: number;
  minimum_confidence: number;
  pass_threshold: number;
  fail_threshold: number;
  minimum_pass_rate: number;
  maximum_consecutive_failures: number;
  zone_y_scale: number;
  min_selected_frames: number;
  max_selected_frames: number;
}

export interface StepStatus {
  name: string;
  status: string;
  detail: string;
}

export interface RunStatus {
  test_id: string;
  test_run_id: string | null;
  status: string;
  progress: number;
  stage: string;
  stage_message: string;
  overall_status: string | null;
  steps: StepStatus[];
  error: string | null;
  reason: string | null;
  recommended_action: string | null;
  preview_image_url?: string | null;
}

export interface FrameRow {
  frame_id: string;
  frame_number: number;
  timestamp_ms: number;
  side: string;
  earlobe_detected: boolean;
  earring_detected: boolean;
  earlobe: { x: number; y: number } | null;
  earring: { x: number; y: number } | null;
  earlobe_confidence: number | null;
  earring_confidence: number | null;
  dx: number | null;
  dy: number | null;
  normalized_distance: number | null;
  status: string;
  reason: string;
  automated_result: string;
  manual_result: string | null;
  reviewer: string | null;
  review_reason: string | null;
  image_url: string;
  annotated_image_url: string | null;
  zone: { ear_width: number; ear_height: number } | null;
  earring_source?: string;
}

export interface QaReport {
  test_run_id: string;
  test_id: string;
  test_name: string;
  overall_status: string;
  reason: string | null;
  recommended_action: string | null;
  layers: Record<string, { status: string; detail: string } | string>;
  statistics: {
    frames_captured: number;
    frames_analyzed: number;
    frames_selected: number;
    frames_passed: number;
    frames_warning: number;
    frames_failed: number;
    pass_rate: number;
    max_consecutive_failures: number;
  };
  thresholds: {
    pass_threshold: number;
    fail_threshold: number;
    minimum_pass_rate: number;
    minimum_confidence?: number;
    maximum_consecutive_failures: number;
    zone_y_scale?: number;
  };
  reference_comparison?: {
    status: string;
    reason?: string;
    sides?: {
      side: string;
      status: string;
      magnitude_reference?: number | null;
      magnitude_actual?: number | null;
      distance_error?: number | null;
      angle_error?: number | null;
      reason?: string;
    }[];
  };
  temporal?: Record<string, { status: string; pass_rate: number; max_consecutive_failures: number; reason: string }>;
  visual_comparison?: Record<string, unknown>;
  application?: { id: string; name: string; type: string; url: string | null } | null;
  jewelry_id?: string | null;
  jewelry_type?: string;
  ear_side?: string;
  reference_filename?: string | null;
  frames: FrameRow[];
  necklace_lay?: {
    status: string;
    final_result: string;
    overall_necklace_lay_accuracy_pct: number;
    ground_truth_accuracy_pct?: number | null;
    reason?: string;
    note?: string;
    checks: Record<string, string>;
    accuracies?: Record<string, number>;
  };
  earring_lay?: {
    status: string;
    final_result: string;
    overall_earring_lay_accuracy_pct: number;
    ground_truth_accuracy_pct?: number | null;
    reason?: string;
    note?: string;
    checks: Record<string, string>;
    accuracies?: Record<string, number>;
  };
  selected_finger?: string | null;
  ring_lay?: {
    status: string;
    final_result: string;
    overall_ring_lay_accuracy_pct: number;
    ground_truth_accuracy_pct?: number | null;
    selected_finger?: string;
    reason?: string;
    note?: string;
    checks: Record<string, string>;
    accuracies?: Record<string, number>;
  };
  bracelet_lay?: {
    status: string;
    final_result: string;
    overall_bracelet_lay_accuracy_pct: number;
    ground_truth_accuracy_pct?: number | null;
    wrist_side?: string;
    bracelet_style?: string;
    reason?: string;
    note?: string;
    checks: Record<string, string>;
    accuracies?: Record<string, number>;
  };
  bangle_lay?: {
    status: string;
    final_result: string;
    overall_bangle_lay_accuracy_pct: number;
    ground_truth_accuracy_pct?: number | null;
    wrist_side?: string;
    bangle_count?: number;
    reason?: string;
    note?: string;
    checks: Record<string, string>;
    accuracies?: Record<string, number>;
  };
}

export interface DashboardData {
  total_tests: number;
  passed: number;
  failed: number;
  warnings: number;
  latest_test: { test_run_id: string; test_id: string; test_name: string; overall_status: string; reason: string | null } | null;
  latest_failure: { test_run_id: string; test_id: string; test_name: string; overall_status: string; reason: string | null } | null;
  average_pass_rate: number | null;
}

const LOOPBACK_API = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(API_URL);

function apiRequest(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...init,
    // Chrome blocks an HTTPS page from calling http://localhost unless the
    // request declares that the target is this computer.
    ...(LOOPBACK_API ? { targetAddressSpace: "loopback" } : {}),
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers || {}),
    },
  } as RequestInit);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await apiRequest(path, init);
  } catch (exc) {
    if (!(exc instanceof TypeError)) throw exc;
    try {
      response = await apiRequest(path, init);
    } catch {
      throw new Error(`The QA API at ${API_URL} did not respond. Start it, then reload this page.`);
    }
  }
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body?.detail?.message || body?.detail || message;
    } catch {
      message = await response.text();
    }
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return undefined as T;
  }
  return response.json();
}

export const api = {
  dashboard: () => request<DashboardData>("/api/v1/dashboard"),
  settings: () => request<Record<string, unknown>>("/api/v1/settings"),
  applications: () => request<ApplicationRecord[]>("/api/v1/applications"),
  tryonForm: () => request<{ name: string; url: string; username: string }>("/api/v1/applications/form"),
  catalog: (body: { url: string; username?: string; password?: string; application_id?: string | null }) =>
    request<CatalogResult>("/api/v1/applications/catalog", { method: "POST", body: JSON.stringify(body) }),
  createApplication: (body: Record<string, unknown>) =>
    request<ApplicationRecord>("/api/v1/applications", { method: "POST", body: JSON.stringify(body) }),
  updateApplication: (id: string, body: { url?: string; username?: string }) =>
    request<ApplicationRecord>(`/api/v1/applications/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteApplication: (id: string) => request<void>(`/api/v1/applications/${id}`, { method: "DELETE" }),
  uploadFaceVideo: (applicationId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ApplicationRecord>(`/api/v1/applications/${applicationId}/face-video`, {
      method: "POST",
      body: form,
    });
  },
  validateApplication: (body: Record<string, unknown>) =>
    request<ValidationResult>("/api/v1/applications/validate", { method: "POST", body: JSON.stringify(body) }),
  references: () => request<ReferenceRecord[]>("/api/v1/references"),
  uploadReference: (file: File, side: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("side", side);
    return request<ReferenceRecord>("/api/v1/references/upload", { method: "POST", body: form });
  },
  deleteReference: (id: string) => request<void>(`/api/v1/references/${id}`, { method: "DELETE" }),
  setReferenceAnchors: (id: string, body: Record<string, unknown>) =>
    request<ReferenceRecord>(`/api/v1/references/${id}/anchors`, { method: "POST", body: JSON.stringify(body) }),
  tests: () => request<TestRecord[]>("/api/v1/tests"),
  getTest: (id: string) => request<TestRecord>(`/api/v1/tests/${id}`),
  createTest: (body: Record<string, unknown>) =>
    request<TestRecord>("/api/v1/tests", { method: "POST", body: JSON.stringify(body) }),
  deleteTest: (id: string) => request<void>(`/api/v1/tests/${id}`, { method: "DELETE" }),
  runTest: (id: string, body: { username?: string; password?: string }) =>
    request<{ test_id: string; test_run_id: string; status: string }>(`/api/v1/tests/${id}/run`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  status: (id: string) => request<RunStatus>(`/api/v1/tests/${id}/status`),
  results: (id: string) => request<QaReport>(`/api/v1/tests/${id}/results`),
  runs: () => request<Record<string, unknown>[]>("/api/v1/runs"),
  deleteRun: (runId: string) => request<void>(`/api/v1/runs/${runId}`, { method: "DELETE" }),
  clearHistory: () => request<{ deleted_runs: number }>("/api/v1/history", { method: "DELETE" }),
  reviewFrame: (testId: string, frameId: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/v1/tests/${testId}/frames/${frameId}/review`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reportUrl: (testId: string) => `${API_URL}/api/v1/tests/${testId}/report`,
  asset: (path: string | null | undefined) => (path ? `${API_URL}${path}` : ""),
};
