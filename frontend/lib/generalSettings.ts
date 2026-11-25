export type ThemeMode = "light" | "dark" | "system";

export type GeneralSettings = {
  appearance: {
    theme: ThemeMode;
  };
};

export const GENERAL_SETTINGS_KEY = "aijewel.qa.generalSettings";
const LEGACY_PASSWORD_HASH_KEY = "aijewel.qa.accountPasswordHash";

export const DEFAULT_GENERAL_SETTINGS: GeneralSettings = {
  appearance: {
    theme: "dark",
  },
};

const THEME_MODES: ThemeMode[] = ["light", "dark", "system"];

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function mergeSettings(raw: unknown): GeneralSettings {
  const base = structuredClone(DEFAULT_GENERAL_SETTINGS);
  if (!isObject(raw) || !isObject(raw.appearance)) return base;
  if (THEME_MODES.includes(raw.appearance.theme as ThemeMode)) {
    base.appearance.theme = raw.appearance.theme as ThemeMode;
  }
  return base;
}

function clearLegacySettings(): void {
  window.localStorage.removeItem(LEGACY_PASSWORD_HASH_KEY);
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
  clearLegacySettings();
}

export function resetGeneralSettings(): GeneralSettings {
  const next = structuredClone(DEFAULT_GENERAL_SETTINGS);
  window.localStorage.setItem(GENERAL_SETTINGS_KEY, JSON.stringify(next));
  clearLegacySettings();
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
