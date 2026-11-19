import { FileVideo, Telescope } from "lucide-react";
import { useState } from "react";
import { cx } from "../lib/format";
import { YouTubeMark } from "./ui";

export function Thumb({ src, kind, className }: { src: string | null | undefined; kind: "youtube" | "local" | "discover"; className?: string }) {
  const [failed, setFailed] = useState(false);
  if (src && !failed) {
    return <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} className={cx("object-cover", className)} />;
  }
  return (
    <div className={cx("flex items-center justify-center bg-gradient-to-br from-violet/25 via-ink-800 to-cyan/15", className)}>
      {kind === "youtube" ? (
        <YouTubeMark className="h-5 w-7 opacity-90" />
      ) : kind === "discover" ? (
        <Telescope className="size-5 text-fg-2" />
      ) : (
        <FileVideo className="size-5 text-fg-2" />
      )}
    </div>
  );
}
