import { createContext, useContext } from "react";
import type { CheckResult, Health } from "./types";

export interface AppState {
  health: Health | null;
  youtube: CheckResult | null;
  refresh: () => void;
}

export const AppContext = createContext<AppState>({ health: null, youtube: null, refresh: () => {} });

export function useApp() {
  return useContext(AppContext);
}
