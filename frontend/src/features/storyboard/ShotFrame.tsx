import type { CSSProperties, ReactNode } from "react";

import { assetUrl } from "@/api/client";
import type { Project, Shot } from "@/api/types";
import { isPortrait } from "@/lib/names";

const bg = (id: string | null | undefined, big: boolean): CSSProperties =>
  id ? { backgroundImage: `url(${assetUrl(id, big ? "preview" : "thumbnail")})` } : {};

/**
 * The shot as the video will frame it, inside a 16:9 box: two halves (diptych), one or two album prints with
 * their handwritten text, a portrait photo on a blurred copy of itself (whole-photo moves), or the photo
 * filling the frame. Used by the storyboard tiles (thumbnails) and the shot editor (previews).
 */
export function ShotFrame({
  project: p,
  shot,
  slot,
  big = false,
  className = "",
  children,
}: {
  project: Project;
  shot: Shot | undefined;
  slot: number;
  big?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  const asset = p.slots[slot]?.asset ?? null;
  const first = shot ? p.slots[shot.slots[0]!]?.asset : asset;
  const kind = shot?.kind;
  let layout: ReactNode = null;

  if (kind === "polaroid" || kind === "polaroid_pair") {
    const ids = kind === "polaroid" ? [first] : [first, shot!.pair];
    layout = (
      <div className={`lay prints ${kind === "polaroid" ? "single" : ""}`}>
        <div className="bgblur" style={bg(first, false)} />
        {ids.map((id, k) => (
          <div key={k} className={`print ${k ? "r2" : "r1"}`}>
            <div className="pimg" style={bg(id, big)} />
            <div className="cap">{shot!.captions?.[k] ?? ""}</div>
          </div>
        ))}
      </div>
    );
  } else if (kind === "diptych") {
    const second = shot!.slots.length > 1 ? p.slots[shot!.slots[1]!]?.asset : shot!.pair;
    layout = (
      <div className="lay">
        <div className="half" style={bg(first, big)} />
        <div className="half" style={bg(second, big)} />
      </div>
    );
  } else if (
    asset &&
    isPortrait(p.assets[asset]) &&
    (kind === "contain_in" || kind === "contain_out" || !kind)
  ) {
    layout = (
      <div className="lay portrait">
        <div className="bgblur" style={bg(asset, false)} />
        <div
          className="pp"
          style={{ ...bg(asset, big), aspectRatio: String(p.assets[asset]?.aspect ?? 0.75) }}
        />
      </div>
    );
  }

  const photoBg = layout ? {} : bg(asset, big);
  const tilt =
    kind === "tilt" && !layout
      ? { backgroundPosition: shot?.tilt_dir === "down" ? "50% 20%" : "50% 30%" }
      : {};
  return (
    <div className={`photo frame-169 ${className}`} style={{ ...photoBg, ...tilt }}>
      {layout}
      {children}
    </div>
  );
}
