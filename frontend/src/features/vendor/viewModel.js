export const PROFILES = ["BALANCED", "COMMERCIAL", "ACCESSIBILITY", "FACILITIES"];
export const LANGUAGES = [{value: "en", label: "English"}, {value: "mr", label: "मराठी"}, {value: "hi", label: "हिंदी"}];
export const RANK_COLORS = {1: "#174b77", 2: "#28658f", 3: "#3b78a3"};
export const pretty = value => (value || "").replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
export const score = value => value == null ? "—" : Number(value).toFixed(1);
export const displayCapacity = (value, t) => value == null ? t("common.notSpecified") : String(value);

