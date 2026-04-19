// Shared profile-draft state for the onboarding flow.

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { Binding, Capabilities, Profile } from "@/lib/types";

const EMPTY_CAPS: Capabilities = {
  head: false, mouth: false, blink: false, brow: false,
  hand: false, voice: false, keyboard: false,
};

export function bindingsFromCapabilities(caps: Capabilities): Binding[] {
  const out: Binding[] = [];
  if (caps.head) {
    out.push({ id: "head_cursor", source: "nose", action: "cursor_xy",
               enabled: true, invert_x: false, invert_y: false });
  }
  if (caps.hand) {
    out.push({ id: "finger_cursor", source: "index_tip", action: "cursor_xy",
               enabled: !caps.head, invert_x: false, invert_y: false });
  }
  let primary = false;
  if (caps.mouth) {
    out.push({ id: "mouth_click", source: "mouth", action: "left_press",
               enabled: true, threshold: 0.08 });
    primary = true;
  }
  if (caps.blink) {
    out.push({ id: "blink_click", source: "blink", action: "left_click",
               enabled: !primary, ear_threshold: 0.18, min_closed_ms: 200 });
    if (!primary) primary = true;
  }
  if (caps.brow) {
    out.push({ id: "brow_click", source: "brow", action: "left_click",
               enabled: !primary, threshold: 0.06 });
  }
  return out;
}

interface ProfileCtx {
  caps: Capabilities;
  setCap: (k: keyof Capabilities, v: boolean) => void;
  bindings: Binding[];
  setBindings: (b: Binding[]) => void;
  voiceEnabled: boolean;
  setVoiceEnabled: (v: boolean) => void;
  toProfile: () => Profile;
}

const Ctx = createContext<ProfileCtx | null>(null);

export function ProfileProvider({ children }: { children: ReactNode }) {
  const [caps, setCaps] = useState<Capabilities>(EMPTY_CAPS);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [voiceEnabled, setVoiceEnabled] = useState(false);

  const value = useMemo<ProfileCtx>(() => ({
    caps,
    setCap: (k, v) => setCaps((c) => ({ ...c, [k]: v })),
    bindings,
    setBindings,
    voiceEnabled,
    setVoiceEnabled,
    toProfile: () => ({
      capabilities: caps,
      bindings: bindings.length > 0 ? bindings : bindingsFromCapabilities(caps),
      voice_enabled: voiceEnabled || caps.voice,
      cursor_sensitivity: 4000,
      filter: { min_cutoff: 1.0, beta: 0.05 },
    }),
  }), [caps, bindings, voiceEnabled]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useProfile() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useProfile outside ProfileProvider");
  return v;
}
