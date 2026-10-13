import React, {useEffect} from "react";
import {Check, X, AlertTriangle} from "lucide-react";
import {toastDuration} from "./feedback.js";

export default function ToastRegion({success = "", error = "", onDismissSuccess, onDismissError, retry}) {
  useEffect(() => {
    if (!success) return undefined;
    const timer = setTimeout(() => onDismissSuccess?.(), toastDuration("success"));
    return () => clearTimeout(timer);
  }, [success, onDismissSuccess]);
  return <div className="toast-region" aria-live="polite" aria-atomic="true">
    {success && <div className="app-toast success" role="status"><Check size={17}/><span>{success}</span><button onClick={onDismissSuccess} aria-label="Dismiss"><X size={15}/></button></div>}
    {error && <div className="app-toast error" role="alert"><AlertTriangle size={17}/><span>{error}</span>{retry && <button className="toast-retry" onClick={retry}>Retry</button>}<button onClick={onDismissError} aria-label="Dismiss"><X size={15}/></button></div>}
  </div>;
}
