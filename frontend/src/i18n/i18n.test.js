import test from "node:test";
import assert from "node:assert/strict";
import {
  CANONICAL_TERMINOLOGY, categoryLabel, formatDate, formatNumber,
  hasDeliberateLanguage, persistLanguage, readStoredLanguage,
  setDocumentLanguage, statusLabel, translate,
} from "./index.js";

function memoryStorage() {
  const values = new Map();
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
}

test("renders English, Marathi, and Hindi interface strings", () => {
  assert.equal(translate("en", "nav.dashboard"), "Dashboard");
  assert.equal(translate("mr", "nav.dashboard"), "डॅशबोर्ड");
  assert.equal(translate("hi", "nav.dashboard"), "डैशबोर्ड");
  assert.equal(translate("mr", "identity.fullName"), "पूर्ण नाव");
  assert.equal(translate("hi", "confirm.cancelRequestTitle"), "यह आवेदन रद्द करें?");
});

test("interpolates dynamic values without translating identifiers", () => {
  assert.match(translate("mr", "recommend.confirmTitle", {zoneId: "NE_F_010"}), /NE_F_010/);
  assert.match(translate("hi", "recommend.eligible", {count: 17}), /17/);
});

test("falls back to English for an untranslated localized key", () => {
  assert.equal(translate("mr", "language.en"), "English");
});

test("language preference survives navigation through storage", () => {
  const storage = memoryStorage();
  persistLanguage(storage, "mr");
  assert.equal(readStoredLanguage(storage), "mr");
  assert.equal(hasDeliberateLanguage(storage), true);
});

test("invalid persisted language safely falls back to English", () => {
  const storage = memoryStorage();
  storage.setItem("nmc_vendor_language", "xx");
  assert.equal(readStoredLanguage(storage), "en");
});

test("document language changes immediately without a reload", () => {
  const documentRef = {documentElement: {lang: "en"}};
  setDocumentLanguage("hi", documentRef);
  assert.equal(documentRef.documentElement.lang, "hi");
});

test("canonical status values are localized for display only", () => {
  const canonical = "NO_VENDING";
  assert.equal(statusLabel("mr", canonical), "विक्री निषिद्ध");
  assert.equal(statusLabel("hi", canonical), "विक्रय निषिद्ध");
  assert.equal(canonical, "NO_VENDING");
  assert.ok(CANONICAL_TERMINOLOGY.statuses.includes(canonical));
});

test("canonical category values are localized for display only", () => {
  const canonical = "vegetable_fruit";
  assert.equal(categoryLabel("mr", canonical), "भाजीपाला व फळे");
  assert.equal(categoryLabel("hi", canonical), "सब्ज़ियाँ और फल");
  assert.equal(canonical, "vegetable_fruit");
});

test("dates and numbers use the selected Indian locale", () => {
  const date = "2026-09-29T10:30:00Z";
  assert.notEqual(formatDate("en", date), formatDate("mr", date));
  assert.equal(formatNumber("hi", 123456), new Intl.NumberFormat("hi-IN").format(123456));
});

test("unknown backend values remain visible through safe display fallback", () => {
  assert.equal(statusLabel("mr", "FUTURE_STATUS"), "FUTURE_STATUS");
});
