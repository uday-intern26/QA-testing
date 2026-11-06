export type ThemeMode = "light" | "dark" | "system";
export type DateFormat = "DD/MM/YYYY" | "MM/DD/YYYY" | "YYYY-MM-DD";
export type TimeFormat = "12h" | "24h";
export type TestingEnvironment = "local" | "development" | "qa" | "staging";
export type ResponseFormat = "json" | "xml";

export type GeneralSettings = {
  account: {
    username: string;
    email: string;
  };
  appearance: {
    theme: ThemeMode;
  };
  notifications: {
    email: boolean;
    inApp: boolean;
    testExecution: boolean;
    failedApiAlerts: boolean;
    system: boolean;
  };
  regional: {
    language: string;
    timeZone: string;
    dateFormat: DateFormat;
    timeFormat: TimeFormat;
  };
  qa: {
    defaultEnvironment: TestingEnvironment;
    apiBaseUrl: string;
    requestTimeoutMs: number;
    responseFormat: ResponseFormat;
    apiRequestLogging: boolean;
    automaticTestExecution: boolean;
    detailedErrorMessages: boolean;
  };
};

export const GENERAL_SETTINGS_KEY = "aijewel.qa.generalSettings";
export const PASSWORD_HASH_KEY = "aijewel.qa.accountPasswordHash";

export const DEFAULT_GENERAL_SETTINGS: GeneralSettings = {
  account: {
    username: "qa-tester",
    email: "tester@aijewel.local",
  },
  appearance: {
    theme: "dark",
  },
  notifications: {
    email: true,
    inApp: true,
    testExecution: true,
    failedApiAlerts: true,
    system: false,
  },
  regional: {
    language: "en-US",
    timeZone: "Asia/Kolkata",
    dateFormat: "DD/MM/YYYY",
    timeFormat: "12h",
  },
  qa: {
    defaultEnvironment: "local",
    apiBaseUrl: "http://127.0.0.1:8000/api/v1",
    requestTimeoutMs: 30000,
    responseFormat: "json",
    apiRequestLogging: true,
    automaticTestExecution: false,
    detailedErrorMessages: true,
  },
};

export const LANGUAGE_OPTIONS = [
  { value: "en-US", label: "English (US)" },
  { value: "en-GB", label: "English (UK)" },
  { value: "hi-IN", label: "Hindi (India)" },
  { value: "fr-FR", label: "French" },
  { value: "de-DE", label: "German" },
  { value: "es-ES", label: "Spanish" },
  { value: "ja-JP", label: "Japanese" },
];

export const TIME_ZONE_OPTIONS = [
  "Asia/Kolkata",
  "UTC",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function mergeSettings(raw: unknown): GeneralSettings {
  const base = structuredClone(DEFAULT_GENERAL_SETTINGS);
  if (!isObject(raw)) return base;
  if (isObject(raw.account)) {
    if (typeof raw.account.username === "string") base.account.username = raw.account.username;
    if (typeof raw.account.email === "string") base.account.email = raw.account.email;
  }
  if (isObject(raw.appearance) && ["light", "dark", "system"].includes(String(raw.appearance.theme))) {
    base.appearance.theme = raw.appearance.theme as ThemeMode;
  }
  if (isObject(raw.notifications)) {
    for (const key of Object.keys(base.notifications) as (keyof GeneralSettings["notifications"])[]) {
      if (typeof raw.notifications[key] === "boolean") {
        base.notifications[key] = raw.notifications[key] as boolean;
      }
    }
  }
  if (isObject(raw.regional)) {
    if (typeof raw.regional.language === "string") base.regional.language = raw.regional.language;
    if (typeof raw.regional.timeZone === "string") base.regional.timeZone = raw.regional.timeZone;
    if (["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"].includes(String(raw.regional.dateFormat))) {
      base.regional.dateFormat = raw.regional.dateFormat as DateFormat;
    }
    if (["12h", "24h"].includes(String(raw.regional.timeFormat))) {
      base.regional.timeFormat = raw.regional.timeFormat as TimeFormat;
    }
  }
  if (isObject(raw.qa)) {
    if (["local", "development", "qa", "staging"].includes(String(raw.qa.defaultEnvironment))) {
      base.qa.defaultEnvironment = raw.qa.defaultEnvironment as TestingEnvironment;
    }
    if (typeof raw.qa.apiBaseUrl === "string") base.qa.apiBaseUrl = raw.qa.apiBaseUrl;
    if (typeof raw.qa.requestTimeoutMs === "number") base.qa.requestTimeoutMs = raw.qa.requestTimeoutMs;
    if (["json", "xml"].includes(String(raw.qa.responseFormat))) {
      base.qa.responseFormat = raw.qa.responseFormat as ResponseFormat;
    }
    for (const key of ["apiRequestLogging", "automaticTestExecution", "detailedErrorMessages"] as const) {
      if (typeof raw.qa[key] === "boolean") base.qa[key] = raw.qa[key] as boolean;
    }
  }
  return base;
}

export function loadGeneralSettings(): GeneralSettings {
  if (typeof window === "undefined") return structuredClone(DEFAULT_GENERAL_SETTINGS);
  try {
    const raw = window.localStorage.getItem(GENERAL_SETTINGS_KEY);
    if (!raw) return structuredClone(DEFAULT_GENERAL_SETTINGS);
    return mergeSettings(JSON.parse(raw));
  } catch {
    return structuredClone(DEFAULT_GENERAL_SETTINGS);
  }
}

export function saveGeneralSettings(settings: GeneralSettings): void {
  window.localStorage.setItem(GENERAL_SETTINGS_KEY, JSON.stringify(settings));
}

export function resetGeneralSettings(): GeneralSettings {
  const next = structuredClone(DEFAULT_GENERAL_SETTINGS);
  window.localStorage.setItem(GENERAL_SETTINGS_KEY, JSON.stringify(next));
  return next;
}

export function resolveTheme(theme: ThemeMode): "light" | "dark" {
  if (theme === "light" || theme === "dark") return theme;
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyTheme(theme: ThemeMode): void {
  if (typeof document === "undefined") return;
  const resolved = resolveTheme(theme);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
  document.documentElement.classList.toggle("dark", resolved === "dark");
  document.documentElement.classList.toggle("light", resolved === "light");
}

export async function hashPassword(password: string): Promise<string> {
  const data = new TextEncoder().encode(password);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function readPasswordHash(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(PASSWORD_HASH_KEY);
}

export async function setPasswordHash(password: string): Promise<void> {
  const digest = await hashPassword(password);
  window.localStorage.setItem(PASSWORD_HASH_KEY, digest);
}

export function clearPasswordHash(): void {
  window.localStorage.removeItem(PASSWORD_HASH_KEY);
}

export type SettingsValidation = {
  ok: boolean;
  messages: string[];
};

export function validateGeneralSettings(settings: GeneralSettings): SettingsValidation {
  const messages: string[] = [];
  const username = settings.account.username.trim();
  const email = settings.account.email.trim();
  if (!username || username.length < 2) messages.push("Username must be at least 2 characters.");
  if (username.length > 80) messages.push("Username must be 80 characters or fewer.");
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) messages.push("Enter a valid email address.");
  try {
    const url = new URL(settings.qa.apiBaseUrl);
    if (!["http:", "https:"].includes(url.protocol)) messages.push("API base URL must use http or https.");
  } catch {
    messages.push("Enter a valid API base URL.");
  }
  if (!Number.isFinite(settings.qa.requestTimeoutMs) || settings.qa.requestTimeoutMs < 1000) {
    messages.push("Request timeout must be at least 1000 ms.");
  }
  if (settings.qa.requestTimeoutMs > 300000) {
    messages.push("Request timeout must be 300000 ms or less.");
  }
  return { ok: messages.length === 0, messages };
}

export type PasswordForm = {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
};

export function validatePasswordChange(form: PasswordForm, hasExistingHash: boolean): SettingsValidation {
  const messages: string[] = [];
  const { currentPassword, newPassword, confirmPassword } = form;
  if (!newPassword && !currentPassword && !confirmPassword) {
    return { ok: true, messages: [] };
  }
  if (hasExistingHash && !currentPassword) {
    messages.push("Enter your current password.");
  }
  if (newPassword.length < 8) messages.push("New password must be at least 8 characters.");
  if (!/[A-Z]/.test(newPassword)) messages.push("New password needs at least one uppercase letter.");
  if (!/[a-z]/.test(newPassword)) messages.push("New password needs at least one lowercase letter.");
  if (!/[0-9]/.test(newPassword)) messages.push("New password needs at least one number.");
  if (newPassword !== confirmPassword) messages.push("New password and confirmation do not match.");
  if (currentPassword && newPassword && currentPassword === newPassword) {
    messages.push("New password must be different from the current password.");
  }
  return { ok: messages.length === 0, messages };
}
