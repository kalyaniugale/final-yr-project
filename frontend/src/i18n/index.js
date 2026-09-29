import en from "./en.js";
import mr from "./mr.js";
import hi from "./hi.js";

export const DEFAULT_LANGUAGE = "en";
export const SUPPORTED_LANGUAGES = ["en", "mr", "hi"];
export const LANGUAGE_STORAGE_KEY = "nmc_vendor_language";
export const LANGUAGE_OVERRIDE_KEY = "nmc_vendor_language_deliberate";
export const LOCALES = {en: "en-IN", mr: "mr-IN", hi: "hi-IN"};
export const dictionaries = {en, mr, hi};

export function normalizeLanguage(language) {
  return SUPPORTED_LANGUAGES.includes(language) ? language : DEFAULT_LANGUAGE;
}

export function interpolate(template, parameters = {}) {
  return String(template).replace(/\{(\w+)\}/g, (_, key) =>
    Object.prototype.hasOwnProperty.call(parameters, key) ? String(parameters[key]) : `{${key}}`
  );
}

export function translate(language, key, parameters = {}) {
  const normalized = normalizeLanguage(language);
  const template = dictionaries[normalized]?.[key] ?? dictionaries.en[key] ?? key;
  return interpolate(template, parameters);
}

const displayValue = (language, prefix, value, fallback) => {
  const key = `${prefix}.${value}`;
  const result = translate(language, key);
  return result === key ? (fallback ?? value ?? translate(language, "common.unknown")) : result;
};
export const statusLabel = (language, value, fallback) => displayValue(language, "status", value, fallback);
export const categoryLabel = (language, value, fallback) => displayValue(language, "category", value || "unknown", fallback);
export const requestTypeLabel = (language, value, fallback) => displayValue(language, "requestType", value, fallback);
export const vendorTypeLabel = (language, value, fallback) => displayValue(language, "vendorType", value, fallback);
export const priorityLabel = (language, value, fallback) => displayValue(language, "priority", value, fallback);
export const factorLabel = (language, key, fallback) => displayValue(language, "factor", key, fallback);
export const factorSummary = (language, key, fallback) => displayValue(language, "factor", `${key}.summary`, fallback);

export function formatDate(language, value) {
  if (!value) return translate(language, "common.notRecorded");
  return new Intl.DateTimeFormat(LOCALES[normalizeLanguage(language)], {
    dateStyle: "medium", timeStyle: "short",
  }).format(new Date(value));
}

export function formatNumber(language, value, options = {}) {
  return new Intl.NumberFormat(LOCALES[normalizeLanguage(language)], options).format(value);
}

export function readStoredLanguage(storage) {
  try { return normalizeLanguage(storage?.getItem(LANGUAGE_STORAGE_KEY)); }
  catch { return DEFAULT_LANGUAGE; }
}

export function persistLanguage(storage, language, deliberate = true) {
  const normalized = normalizeLanguage(language);
  try {
    storage?.setItem(LANGUAGE_STORAGE_KEY, normalized);
    if (deliberate) storage?.setItem(LANGUAGE_OVERRIDE_KEY, "true");
  } catch { /* Storage may be unavailable in privacy modes. */ }
  return normalized;
}

export function hasDeliberateLanguage(storage) {
  try { return storage?.getItem(LANGUAGE_OVERRIDE_KEY) === "true"; }
  catch { return false; }
}

export function setDocumentLanguage(language, documentRef = globalThis.document) {
  const normalized = normalizeLanguage(language);
  if (documentRef?.documentElement) documentRef.documentElement.lang = normalized;
  return normalized;
}

// Canonical backend codes remain unchanged. These helpers are display-only and
// are intentionally reusable by a future WhatsApp adapter.
export const CANONICAL_TERMINOLOGY = Object.freeze({
  statuses: ["OPEN", "FULL", "CLOSED", "SUSPENDED", "RESTRICTED", "NO_VENDING", "PENDING", "APPROVED", "REJECTED", "CANCELLED", "ACTIVE", "RELEASED"],
  categories: ["vegetable_fruit", "flower", "clothing", "general_goods", "food", "other", "unknown"],
  requestTypes: ["NEW_ALLOCATION", "RELOCATION"],
  factors: ["business", "commercial", "access", "facilities", "preference", "historical"],
});
