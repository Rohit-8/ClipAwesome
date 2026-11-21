import type { CSSProperties } from "react";
import { useCallback, useEffect, useState } from "react";
import { MobileNav, Sidebar, TopBar } from "./components/Sidebar";
import { ToastProvider } from "./components/Toast";
import { api } from "./lib/api";
import { AppContext } from "./lib/app-context";
import { useRoute } from "./lib/router";
import type { CheckResult, Health } from "./lib/types";
import { DownloadsPage } from "./pages/Downloads";
import { EditorPage } from "./pages/Editor";
import { HistoryPage } from "./pages/History";
import { JobView } from "./pages/JobView";
import { Results } from "./pages/Results";
import { SettingsPage } from "./pages/Settings";
import { Studio } from "./pages/Studio";

const SIDEBAR_KEY = "clipawesome.sidebar-collapsed";

export default function App() {
  const { segments } = useRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const [youtube, setYoutube] = useState<CheckResult | null>(null);
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(SIDEBAR_KEY) === "1");

  const toggleSidebar = () =>
    setCollapsed((c) => {
      localStorage.setItem(SIDEBAR_KEY, c ? "0" : "1");
      return !c;
    });

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
  else if (head === "download") {
    page = <DownloadsPage />;
    active = "download";
  } else if (head === "editor") {
    page = <EditorPage />;
    active = "editor";
  } else if (head === "history") {
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
        {/* --sidebar-w lets fixed elements (e.g. the Settings save bar) centre on the content area. */}
        <div className="flex h-full flex-col" style={{ "--sidebar-w": collapsed ? "72px" : "248px" } as CSSProperties}>
          <TopBar collapsed={collapsed} onToggle={toggleSidebar} />
          <div className="flex min-h-0 flex-1">
            <Sidebar active={active} collapsed={collapsed} />
            <main className="min-w-0 flex-1 overflow-y-auto">
              <MobileNav active={active} />
              {page}
            </main>
          </div>
        </div>
      </ToastProvider>
    </AppContext.Provider>
  );
}
