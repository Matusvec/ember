export type CapabilityId =
  | "head"
  | "mouth"
  | "blink"
  | "brow"
  | "hand"
  | "voice"
  | "keyboard";

export const CAPABILITY_IDS: CapabilityId[] = [
  "head", "mouth", "blink", "brow", "hand", "voice", "keyboard",
];

export interface Capabilities {
  head: boolean;
  mouth: boolean;
  blink: boolean;
  brow: boolean;
  hand: boolean;
  voice: boolean;
  keyboard: boolean;
}

export interface Binding {
  id: string;
  source: string;
  action: string;
  enabled: boolean;
  [k: string]: unknown;
}

export interface Profile {
  capabilities: Capabilities;
  bindings: Binding[];
  voice_enabled: boolean;
  cursor_sensitivity?: number;
  filter?: { min_cutoff: number; beta: number };
}

export interface ServerConfig {
  elevenlabs_agent_id: string;
  elevenlabs_voice_id: string;
  profile_exists: boolean;
}
