import { createContext, useContext, useEffect, useMemo, useState } from "react";

export const DEFAULT_LANG = "ja";
export const SUPPORTED_LANGS = ["ja", "en"];

const LangContext = createContext({ lang: DEFAULT_LANG, setLang: () => {} });

function storedValue(key, fallback) {
  if (typeof window === "undefined") return fallback;
  try {
    return window.localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

export function LangProvider({ children }) {
  const [lang, setLangState] = useState(() => {
    const value = storedValue("cg.lang", DEFAULT_LANG);
    return SUPPORTED_LANGS.includes(value) ? value : DEFAULT_LANG;
  });

  const setLang = (value) => {
    if (SUPPORTED_LANGS.includes(value)) setLangState(value);
  };

  useEffect(() => {
    document.documentElement.lang = lang;
    document.title = "DeepWiki";
    try {
      window.localStorage.setItem("cg.lang", lang);
    } catch {
      // Storage can be unavailable in privacy modes; the in-memory choice still works.
    }
  }, [lang]);

  const value = useMemo(() => ({ lang, setLang }), [lang]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useLang() {
  return useContext(LangContext);
}

export function useT(dict) {
  const { lang } = useLang();
  const base = dict.ja || {};
  const active = dict[lang] || base;
  return { ...base, ...active };
}

export function LangToggle({ className = "" }) {
  const { lang, setLang } = useLang();
  return (
    <button
      type="button"
      onClick={() => setLang(lang === "ja" ? "en" : "ja")}
      aria-label={lang === "ja" ? "Switch to English" : "日本語に切り替え"}
      className={`rounded-md border border-rule bg-panel px-2.5 py-1.5 text-xs font-semibold text-ink-muted transition hover:border-rule-strong hover:text-ink ${className}`}
    >
      {lang === "ja" ? "EN" : "日本語"}
    </button>
  );
}

export function useResolvedTheme() {
  const [theme, setThemeState] = useState(() => storedValue("cg.theme", "system"));
  const [systemDark, setSystemDark] = useState(() =>
    typeof window !== "undefined"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false,
  );
  const safeTheme = ["light", "dark", "system"].includes(theme) ? theme : "system";
  const resolvedTheme = safeTheme === "system" ? (systemDark ? "dark" : "light") : safeTheme;

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event) => setSystemDark(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.theme = resolvedTheme;
    root.classList.toggle("dark", resolvedTheme === "dark");
    root.style.colorScheme = resolvedTheme;
    try {
      window.localStorage.setItem("cg.theme", safeTheme);
    } catch {
      // Keep the current in-memory theme when storage is unavailable.
    }
  }, [resolvedTheme, safeTheme]);

  const setTheme = (value) => {
    if (["light", "dark", "system"].includes(value)) setThemeState(value);
  };
  return { theme: safeTheme, setTheme, resolvedTheme };
}
