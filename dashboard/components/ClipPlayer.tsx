"use client";

import { API_BASE, type Clip } from "../lib/api";

/**
 * Plays the CCTV segment around a flagged event. When footage for the timestamp
 * isn't available (outside the short sample clip, or videos absent on a fresh
 * clone) it falls back to the text reference + the `make clip` hint.
 */
export default function ClipPlayer({ clip, review }: { clip?: Clip | null; review?: string }) {
  if (clip?.available) {
    const src = `${API_BASE}${clip.video_url}#t=${clip.start_s},${clip.end_s}`;
    return (
      <div className="mt-3 overflow-hidden rounded-lg border border-border bg-bg">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video
          key={src}
          src={src}
          controls
          autoPlay
          muted
          playsInline
          preload="metadata"
          className="max-h-80 w-full bg-black"
        />
        <div className="flex items-center justify-between px-3 py-2 text-[11px] text-slate-500">
          <span className="uppercase tracking-wide text-slate-400">{clip.camera}</span>
          <span className="tabular-nums">clip {clip.start_s}s – {clip.end_s}s</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-lg border border-border bg-bg px-3 py-3 text-xs text-slate-500">
      <span className="text-slate-400">Footage not available for this timestamp.</span>
      {review && <div className="mt-1">{review}</div>}
      <div className="mt-1">
        Pull it from the secured source: <code className="text-accent-hover">make clip CAM={clip?.camera ?? "camN"} AT=&lt;sec&gt;</code>
      </div>
    </div>
  );
}
