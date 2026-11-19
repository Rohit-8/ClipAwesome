import { useCallback, useEffect, useState } from "react";
import { MobileNav, Sidebar } from "./components/Sidebar";
import { ToastProvider } from "./components/Toast";
import { api } from "./lib/api";
import { AppContext } from "./lib/app-context";
import { useRoute } from "./lib/router";
import type { CheckResult, Health } from "./lib/types";
import { HistoryPage } from "./pages/History";
import { JobView } from "./pages/JobView";
import { Results } from "./pages/Results";
import { SettingsPage } from "./pages/Settings";
import { Studio } from "./pages/Studio";

export default function App() {
  const { segments } = useRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const [youtube, setYoutube] = useState<CheckResult | null>(null);

  const refresh = useCallback(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api
      .checkYouTube()
      .then(setYoutube)
      .catch((e: Error) => setYoutube({ ok: false, message: e.message }));
  }, []);

  useEffect(refresh, [refresh]);

  const [head, id] = segments;
  let page;
  let active = "studio";
  if (head === "job" && id) page = <JobView key={id} id={id} />;
  else if (head === "analysis" && id) page = <Results key={id} id={id} />;
  else if (head === "history") {
    page = <HistoryPage />;
    active = "history";
  } else if (head === "settings") {
    page = <SettingsPage />;
    active = "settings";
  } else page = <Studio />;
  if (head === "analysis" || head === "job") active = "";

  return (
    <AppContext.Provider value={{ health, youtube, refresh }}>
      <ToastProvider>
        <div className="flex min-h-full">
          <Sidebar active={active} />
          <main className="min-w-0 flex-1">
            <MobileNav active={active} />
            {page}
          </main>
        </div>
      </ToastProvider>
    </AppContext.Provider>
  );
}
