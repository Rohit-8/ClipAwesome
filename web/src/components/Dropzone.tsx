import { Captions, FileVideo, UploadCloud, X } from "lucide-react";
import { useRef, useState } from "react";
import type { DragEvent } from "react";
import { cx } from "../lib/format";

const MEDIA_ACCEPT = ".mp4,.mkv,.mov,.webm,.avi,.m4v,.wmv,.flv,.mpg,.mpeg,.ts,.mp3,.wav,.m4a,.flac,.ogg,.opus,.aac";
const SUB_ACCEPT = ".srt,.vtt";

function sizeLabel(bytes: number) {
  if (bytes > 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
}

export function Dropzone({
  file,
  subtitle,
  onFile,
  onSubtitle,
}: {
  file: File | null;
  subtitle: File | null;
  onFile: (f: File | null) => void;
  onSubtitle: (f: File | null) => void;
}) {
  const [drag, setDrag] = useState(false);
  const mediaInput = useRef<HTMLInputElement>(null);
  const subInput = useRef<HTMLInputElement>(null);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    for (const f of Array.from(e.dataTransfer.files)) {
      const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
      if (SUB_ACCEPT.includes(ext)) onSubtitle(f);
      else if (MEDIA_ACCEPT.includes(ext)) onFile(f);
    }
  };

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => mediaInput.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && mediaInput.current?.click()}
        className={cx(
          "group relative flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-10 text-center transition-all duration-200",
          drag ? "border-violet/70 bg-violet/[0.08]" : "border-white/[0.12] bg-black/15 hover:border-white/25 hover:bg-white/[0.02]",
        )}
      >
        <input ref={mediaInput} type="file" accept={MEDIA_ACCEPT} className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        {file ? (
          <div className="flex items-center gap-3">
            <div className="flex size-11 items-center justify-center rounded-xl bg-accent/90 text-white shadow-lg shadow-violet/20">
              <FileVideo className="size-5" />
            </div>
            <div className="text-left">
              <div className="max-w-[340px] truncate text-sm font-medium text-fg">{file.name}</div>
              <div className="text-[12px] text-fg-3">{sizeLabel(file.size)} · click to replace</div>
            </div>
            <button
              type="button"
              aria-label="Remove file"
              onClick={(e) => {
                e.stopPropagation();
                onFile(null);
              }}
              className="ml-2 rounded-lg p-1.5 text-fg-3 transition hover:bg-white/[0.08] hover:text-fg"
            >
              <X className="size-4" />
            </button>
          </div>
        ) : (
          <>
            <div className="mb-3 flex size-12 items-center justify-center rounded-2xl bg-white/[0.05] ring-1 ring-white/[0.08] transition group-hover:scale-105">
              <UploadCloud className="size-5 text-fg-2" />
            </div>
            <div className="text-sm font-medium text-fg">Drop a video or audio file</div>
            <div className="mt-1 text-[12.5px] text-fg-3">MP4, MKV, MOV, WebM, MP3, WAV… analysed locally on your machine</div>
          </>
        )}
      </div>

      <div className="flex items-center justify-between rounded-xl border border-white/[0.06] bg-black/10 px-3.5 py-2.5">
        <div className="flex items-center gap-2.5 text-[13px]">
          <Captions className="size-4 text-fg-3" />
          {subtitle ? (
            <span className="text-fg">{subtitle.name}</span>
          ) : (
            <span className="text-fg-3">Optional subtitles (.srt / .vtt) — skips transcription</span>
          )}
        </div>
        <input ref={subInput} type="file" accept={SUB_ACCEPT} className="hidden" onChange={(e) => onSubtitle(e.target.files?.[0] ?? null)} />
        {subtitle ? (
          <button type="button" onClick={() => onSubtitle(null)} className="text-[12.5px] text-fg-3 hover:text-fg">
            Remove
          </button>
        ) : (
          <button type="button" onClick={() => subInput.current?.click()} className="text-[12.5px] font-medium text-[#c4b5fd] hover:text-white">
            Add file
          </button>
        )}
      </div>
    </div>
  );
}
