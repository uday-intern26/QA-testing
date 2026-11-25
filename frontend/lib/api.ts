export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

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
  debug_mode?: boolean;
  debug_options?: Record<string, number | boolean> | null;
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
  debug_image_url?: string | null;
  zone: { ear_width: number; ear_height: number } | null;
  earring_source?: string;
  jewelry_category?: string | null;
  detected_body_parts?: string[];
  required_body_parts?: string[];
  body_confidence?: number | null;
  frame_quality_score?: number | null;
  selection_status?: string | null;
  rejection_reasons?: string[];
  rejection_sources?: Record<string, string>;
  jewelry_diagnostics?: JewelryDiagnostics | null;
  landmark_validation?: LandmarkFrameValidation | null;
  failure_reason?: string | null;
  landmarks_url?: string | null;
  matching_score?: number | null;
  placement_accuracy?: number | null;
  placement_rank?: number | null;
  best_match?: boolean;
  top_match?: boolean;
  tracing_points_valid?: boolean;
}

export interface JewelryDiagnostics {
  anchor_source?: string | null;
  anchor_stage?: string | null;
  qa_status?: string | null;
  glb_loaded?: boolean | null;
  mesh_visible?: boolean | null;
  transform_computed?: boolean | null;
  camera_found?: boolean | null;
  anchor_projected?: boolean | null;
  notes?: string[];
}

export interface FrameLandmarks {
  frame_number: number;
  jewelry_type: string;
  uses_hand_landmarks: boolean;
  face: number[][];
  hand: number[][];
  contours: Record<string, number[]>;
  selected_landmarks: Record<string, number>;
}

export interface DebugTolerances {
  position_tolerance_px: number | null;
  position_tolerance_normalized: number;
  rotation_tolerance_deg: number;
  scale_min_ratio: number;
  scale_max_ratio: number;
  minimum_landmark_confidence: number;
  minimum_valid_frame_percentage: number;
  max_consecutive_tracking_failures: number;
  minimum_stable_frames: number;
  max_interframe_jump_normalized: number;
}

export interface DebugDisplayOptions {
  show_face_mesh: boolean;
  show_landmark_numbers: boolean;
  highlight_selected_landmark: boolean;
  show_expected_point: boolean;
  show_actual_point: boolean;
  show_deviation: boolean;
  show_confidence: boolean;
  show_frame_validation: boolean;
  landmark_number_step: number;
}

export interface DebugProfile {
  jewelry_type: string;
  label: string;
  body_region: string;
  tolerances: DebugTolerances;
  display: DebugDisplayOptions;
}

export interface LandmarkCheck {
  status: string;
  detail: string;
  measured?: number | null;
  tolerance?: number | null;
}

export interface LandmarkFrameValidation {
  frame_number: number;
  timestamp_ms: number;
  side: string;
  jewelry_type: string;
  landmark_index: number | null;
  expected: { x: number; y: number } | null;
  actual: { x: number; y: number } | null;
  expected_px: number[] | null;
  actual_px: number[] | null;
  position_error_px: number | null;
  position_error_normalized: number | null;
  position_error_body_relative?: number | null;
  landmark_confidence: number | null;
  jewelry_confidence: number | null;
  rotation_deg: number | null;
  scale_ratio: number | null;
  checks: Record<string, LandmarkCheck>;
  status: string;
  failure_reason: string | null;
  anchor_source?: string | null;
  diagnostics?: JewelryDiagnostics | null;
}

export interface LandmarkSideSummary {
  jewelry_type: string;
  overall_status: string;
  failure_reason: string | null;
  checks: Record<string, LandmarkCheck>;
  metrics: {
    total_frames: number;
    valid_frames: number;
    testable_frames: number;
    ignored_frames: number;
    tracking_failures: number;
    max_consecutive_failures: number;
    position_jumps: number;
    longest_stable_frames: number;
    valid_frame_percentage: number;
    average_position_error_px: number | null;
    max_position_error_px: number | null;
    average_position_error_normalized: number | null;
    max_position_error_normalized: number | null;
  };
  anchor_sources?: Record<string, number>;
  anchor_stages?: Record<string, number>;
  tolerances: DebugTolerances;
  frames: LandmarkFrameValidation[];
}

export interface LandmarkValidationReport {
  enabled: boolean;
  debug_mode: boolean;
  enforced: boolean;
  overall_status: string;
  failure_reason: string | null;
  profile: DebugProfile;
  sides: Record<string, LandmarkSideSummary>;
  debug_frames: { frame_number: number; side: string; status: string; failure_reason: string | null; path: string }[];
  failed_debug_frames: { frame_number: number; side: string; status: string; failure_reason: string | null; path: string }[];
}

export interface ClosestFrame {
  frame_number: number;
  status: string;
  review_label: string;
  normalized_distance: number | null;
  placement_gap: number | null;
  pass_threshold: number;
  fail_threshold?: number;
  reason?: string | null;
  body_confidence?: number | null;
  earring_confidence?: number | null;
  earlobe?: { x: number; y: number } | null;
  earring_anchor?: { x: number; y: number } | null;
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
    frames_not_testable?: number;
    frames_rejected?: number;
    frames_usable?: number;
    minimum_required_frames?: number | null;
    target_frames?: number | null;
    near_pass_frames?: number;
    best_placement_distance?: number | null;
    frames_detected?: number;
    frames_with_tracing_points?: number;
    average_tracing_accuracy?: number | null;
    best_frame_number?: number | null;
    top_frame_numbers?: number[];
    blank_dropped?: number;
    testable_frames?: number;
    pass_rate: number;
    pass_percentage?: number;
    earring_accuracy?: number | null;
    necklace_accuracy?: number | null;
    max_consecutive_failures: number;
    jewelry_type?: string;
    required_body_parts?: string[];
    body_parts_detected_frames?: number;
    jewelry_lay_seconds?: number | null;
  };
  thresholds: {
    pass_threshold: number;
    fail_threshold: number;
    minimum_pass_rate: number;
    minimum_confidence?: number;
    maximum_consecutive_failures: number;
    zone_y_scale?: number;
    euclidean_pass?: number;
    euclidean_fail?: number;
  };
  landmark_validation?: LandmarkValidationReport;
  placement_validation?: {
    jewelry_type?: string;
    overall_status?: string;
    components?: Record<
      string,
      {
        status?: string;
        x?: number | null;
        y?: number | null;
        placement_error?: number | null;
        head_angle_deg?: number | null;
        reason?: string | null;
      }
    >;
    summary?: {
      total_frames?: number;
      passed_frames?: number;
      warning_frames?: number;
      failed_frames?: number;
      not_testable_frames?: number;
      testable_frames?: number;
      overall_result?: string;
      pass_percentage?: number;
      earring_accuracy?: number | null;
      necklace_accuracy?: number | null;
    };
    thresholds?: {
      euclidean_pass?: number;
      euclidean_warning?: number;
      euclidean_fail_above?: number;
      frontal_yaw_deg?: number;
      earring_pass_band?: { x: number[]; y: number[] };
      earring_fail_band?: { x: number[]; y: number[] };
      necklace_pass_band?: { x: number[]; y: number[] };
      necklace_fail_band?: { x: number[]; y: number[] };
      angle_pass_points?: Record<string, Record<string, number[]>>;
    };
    frames?: Record<string, unknown>[];
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
  closest_frames?: ClosestFrame[];
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
    const raw = await response.text();
    if (raw) {
      try {
        const body = JSON.parse(raw) as { detail?: { message?: string } | string };
        const detail = body?.detail;
        message =
          (typeof detail === "object" && detail?.message) ||
          (typeof detail === "string" ? detail : null) ||
          raw;
      } catch {
        message = raw;
      }
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
  frameLandmarks: (url: string) => request<FrameLandmarks>(url),
  runs: () => request<Record<string, unknown>[]>("/api/v1/runs"),
  deleteRun: (runId: string) => request<void>(`/api/v1/runs/${runId}`, { method: "DELETE" }),
  clearHistory: () => request<{ deleted_runs: number }>("/api/v1/history", { method: "DELETE" }),
  reviewFrame: (testId: string, frameId: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/v1/tests/${testId}/frames/${frameId}/review`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  reportUrl: (testId: string) => `${API_URL}/api/v1/tests/${testId}/report`,
  asset: (path: string | null | undefined) => {
    if (!path) return "";
    if (path.startsWith("http://") || path.startsWith("https://")) return path;
    // Same-origin path so the dashboard on port 8000 loads the proxied image.
    return path.startsWith("/") ? path : `${API_URL}/${path}`;
  },
};
