import React from "react";

import {pretty} from "./viewModel.js";

export function StatusBadge({status}) {
  return <span className={`admin-status status-${String(status).toLowerCase()}`}>{pretty(status)}</span>;
}

export function DataTable({children}) {
  return <div className="admin-table-wrap"><table className="admin-table">{children}</table></div>;
}

