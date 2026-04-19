// Configure — shows detected capabilities + proposed mapping. Lets the user
// either confirm and save, or talk to the ElevenLabs ConvAI widget to adjust.

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Shell } from "@/components/Shell";
import { useProfile, bindingsFromCapabilities } from "@/state/profile";
import { fetchConfig, saveProfile } from "@/lib/api";
import type { Binding, Capabilities } from "@/lib/types";

const CAP_LABELS: Record<keyof Capabilities, string> = {
  head: "Head motion",
  mouth: "Open mouth",
  blink: "Blink",
  brow: "Eyebrow raise",
  hand: "Hand / finger",
  voice: "Voice",
  keyboard: "Keyboard",
};

function describeBinding(b: Binding): string {
  const srcLabel: Record<string, string> = {
    nose: "head", mouth: "mouth", blink: "blink",
    brow: "eyebrows", index_tip: "finger",
  };
  const actLabel: Record<string, string> = {
    cursor_xy: "→ move cursor",
    left_press: "→ click (hold to drag)",
    left_click: "→ click",
    right_click: "→ right-click",
  };
  return `${srcLabel[b.source] ?? b.source} ${actLabel[b.action] ?? "→ " + b.action}`;
}

export default function Configure() {
  const nav = useNavigate();
  const { caps, bindings, setBindings, voiceEnabled, setVoiceEnabled, toProfile } = useProfile();
  const [agentId, setAgentId] = useState("");
  const [saving, setSaving] = useState(false);
  const [showAgent, setShowAgent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchConfig()
      .then((c) => setAgentId(c.elevenlabs_agent_id))
      .catch(() => setAgentId(""));
  }, []);

  useEffect(() => {
    if (bindings.length === 0) setBindings(bindingsFromCapabilities(caps));
    if (caps.voice) setVoiceEnabled(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Inject ElevenLabs ConvAI script once if opening the agent panel.
  useEffect(() => {
    if (!showAgent) return;
    const id = "elevenlabs-convai-script";
    if (document.getElementById(id)) return;
    const s = document.createElement("script");
    s.id = id;
    s.src = "https://unpkg.com/@elevenlabs/convai-widget-embed";
    s.async = true;
    document.body.appendChild(s);
  }, [showAgent]);

  async function confirm() {
    setSaving(true);
    setError(null);
    try {
      await saveProfile(toProfile());
      nav("/practice");
    } catch (e: any) {
      setError(e?.message ?? "save failed");
    } finally {
      setSaving(false);
    }
  }

  const active = bindings.filter((b) => b.enabled);

  return (
    <Shell>
      <div className="max-w-5xl mx-auto">
        <div className="text-center mb-10">
          <h1 className="text-4xl font-semibold tracking-tight">Here's what I found</h1>
          <p className="mt-2 text-muted">Confirm your setup or talk it through with me.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="card p-8">
            <div className="text-xs uppercase tracking-[0.2em] text-ember font-medium">You can use</div>
            <ul className="mt-6 space-y-3">
              {(Object.keys(CAP_LABELS) as (keyof Capabilities)[]).map((k) => (
                <li key={k} className="flex items-center gap-3">
                  <span className={
                    "h-2.5 w-2.5 rounded-full " +
                    (caps[k] ? "bg-ok" : "bg-border/50")
                  } />
                  <span className={caps[k] ? "text-text" : "text-dim line-through"}>
                    {CAP_LABELS[k]}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div className="card p-8">
            <div className="text-xs uppercase tracking-[0.2em] text-ember font-medium">Ember will set up</div>
            {active.length === 0 ? (
              <p className="mt-6 text-warn">Nothing detected yet — try again.</p>
            ) : (
              <ul className="mt-6 space-y-3">
                {active.map((b, i) => (
                  <li key={i} className="flex items-start gap-3">
                    <span className="mt-2 h-1.5 w-1.5 rounded-full bg-ember" />
                    <span className="text-text">{describeBinding(b)}</span>
                  </li>
                ))}
                {voiceEnabled && (
                  <li className="flex items-start gap-3">
                    <span className="mt-2 h-1.5 w-1.5 rounded-full bg-ember" />
                    <span className="text-text">voice commands after setup</span>
                  </li>
                )}
              </ul>
            )}
          </div>
        </div>

        {error && <div className="text-warn text-center mt-6">{error}</div>}

        <div className="flex flex-wrap items-center justify-center gap-3 mt-10">
          <button className="btn btn-primary text-base px-6 py-3.5" onClick={confirm} disabled={saving}>
            {saving ? "Saving..." : "Looks good"}
            <span aria-hidden>→</span>
          </button>
          {agentId && caps.voice && (
            <button className="btn btn-ghost" onClick={() => setShowAgent((v) => !v)}>
              {showAgent ? "Hide voice assistant" : "Talk to change this"}
            </button>
          )}
          <button className="btn btn-ghost" onClick={() => nav("/discover")}>
            Start over
          </button>
        </div>

        {showAgent && agentId && (
          <div className="card mt-10 p-6">
            <div className="text-xs uppercase tracking-[0.2em] text-ember font-medium mb-3">
              Voice setup
            </div>
            <p className="text-muted text-sm mb-4">
              Say what you want — interrupt me anytime. "Looks good" saves it.
            </p>
            <div dangerouslySetInnerHTML={{
              __html: `<elevenlabs-convai agent-id="${agentId}"></elevenlabs-convai>`,
            }} />
          </div>
        )}
      </div>
    </Shell>
  );
}
