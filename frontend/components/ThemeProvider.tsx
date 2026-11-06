"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  applyTheme,
  loadGeneralSettings,
  type GeneralSettings,
  type ThemeMode,
} from "@/lib/generalSettings";

type ThemeContextValue = {
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  refreshFromStorage: () => void;
};

const ThemeContext = createContext<ThemeContextValue>({
  theme: "dark",
  setTheme: () => undefined,
  refreshFromStorage: () => undefined,
});

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>("dark");

  const refreshFromStorage = useCallback(() => {
    const settings: GeneralSettings = loadGeneralSettings();
    setThemeState(settings.appearance.theme);
    applyTheme(settings.appearance.theme);
  }, []);

  const setTheme = useCallback((next: ThemeMode) => {
    setThemeState(next);
    applyTheme(next);
  }, []);

  useEffect(() => {
    refreshFromStorage();
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = () => {
      const settings = loadGeneralSettings();
      if (settings.appearance.theme === "system") applyTheme("system");
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [refreshFromStorage]);

  const value = useMemo(() => ({ theme, setTheme, refreshFromStorage }), [theme, setTheme, refreshFromStorage]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return useContext(ThemeContext);
}
