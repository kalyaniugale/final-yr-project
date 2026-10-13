import {BarChart3, ClipboardList, Layers, Users, MapPin} from "lucide-react";
export const TABS = [
  {id: "overview", label: "Overview", icon: BarChart3},
  {id: "requests", label: "Pending Requests", icon: ClipboardList},
  {id: "zones", label: "Zone Management", icon: Layers},
  {id: "allocations", label: "Allocations", icon: Users},
  {id: "map", label: "Map / Zone Explorer", icon: MapPin},
];
export const STATUS_COLORS = {
  OPEN: "#218657", FULL: "#b45309", CLOSED: "#64748b", SUSPENDED: "#b91c1c",
  RESTRICTED: "#7c3aed", NO_VENDING: "#334155",
};
export const pretty = value => String(value || "").replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());
export const display = value => value == null ? "—" : value;
export const when = value => value ? new Date(value).toLocaleString() : "—";

