import React, {createContext, useCallback, useContext, useEffect, useMemo, useState} from "react";
import {
  DEFAULT_LANGUAGE, hasDeliberateLanguage, normalizeLanguage,
  persistLanguage, readStoredLanguage, setDocumentLanguage, translate,
} from "./index.js";

const I18nContext = createContext(null);

export function I18nProvider({children}) {
  const [language, setLanguageState] = useState(() =>
    typeof window === "undefined" ? DEFAULT_LANGUAGE : readStoredLanguage(window.localStorage)
  );

  const selectLanguage = useCallback((next, {deliberate = true} = {}) => {
    const normalized = normalizeLanguage(next);
    setLanguageState(normalized);
    if (typeof window !== "undefined") persistLanguage(window.localStorage, normalized, deliberate);
  }, []);

  const applyProfileLanguage = useCallback(savedLanguage => {
    if (!savedLanguage || typeof window === "undefined") return;
    if (!hasDeliberateLanguage(window.localStorage)) {
      const normalized = persistLanguage(window.localStorage, savedLanguage, false);
      setLanguageState(normalized);
    }
  }, []);

  useEffect(() => { setDocumentLanguage(language); }, [language]);
  const t = useCallback((key, parameters) => translate(language, key, parameters), [language]);
  const value = useMemo(() => ({language, t, selectLanguage, applyProfileLanguage}), [language, t, selectLanguage, applyProfileLanguage]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside I18nProvider");
  return context;
}
