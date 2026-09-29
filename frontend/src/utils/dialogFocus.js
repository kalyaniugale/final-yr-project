import {useEffect} from "react";

export function focusCycleIndex(currentIndex, count, backwards = false) {
  if (count <= 0) return -1;
  if (backwards) return currentIndex <= 0 ? count - 1 : currentIndex - 1;
  return currentIndex >= count - 1 ? 0 : currentIndex + 1;
}

export function useDialogFocus(active, selector) {
  useEffect(() => {
    if (!active) return undefined;
    const previous = document.activeElement;
    const dialog = document.querySelector(selector);
    if (!dialog) return undefined;
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    const focusables = () => [...dialog.querySelectorAll(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )];
    focusables()[0]?.focus();
    const trap = event => {
      if (event.key !== "Tab") return;
      const items = focusables();
      if (!items.length) return;
      const index = Math.max(0, items.indexOf(document.activeElement));
      event.preventDefault();
      items[focusCycleIndex(index, items.length, event.shiftKey)]?.focus();
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      previous?.focus?.();
    };
  }, [active, selector]);
}
