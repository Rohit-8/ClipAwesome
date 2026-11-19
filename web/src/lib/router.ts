import { useSyncExternalStore } from "react";

function subscribe(cb: () => void) {
  window.addEventListener("hashchange", cb);
  return () => window.removeEventListener("hashchange", cb);
}

function snapshot() {
  return window.location.hash.replace(/^#\/?/, "");
}

/** Returns the current hash route split into path segments plus the query string params. */
export function useRoute(): { segments: string[]; params: URLSearchParams } {
  const raw = useSyncExternalStore(subscribe, snapshot);
  const [path, query = ""] = raw.split("?");
  return { segments: path.split("/").filter(Boolean).map(decodeURIComponent), params: new URLSearchParams(query) };
}

export function navigate(path: string, replace = false) {
  const target = `#/${path.replace(/^\//, "")}`;
  if (replace) window.location.replace(target);
  else window.location.hash = target;
}
