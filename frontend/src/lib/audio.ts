/**
 * Web Audio API synthesizer for IBVAP Tactical Audio Alarms.
 * Synthesizes crisp military/tactical chimes with zero external audio dependencies.
 */

let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (AudioContextClass) {
      audioCtx = new AudioContextClass();
    }
  }
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume().catch(() => {});
  }
  return audioCtx;
}

export function isAudioMuted(): boolean {
  if (typeof window === "undefined") return true;
  return localStorage.getItem("ibvap_audio_muted") === "true";
}

export function setAudioMuted(muted: boolean): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("ibvap_audio_muted", muted ? "true" : "false");
}

export function playTacticalAlert(threatLevel: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | string): void {
  if (isAudioMuted()) return;
  const ctx = getAudioContext();
  if (!ctx) return;

  const now = ctx.currentTime;
  const level = threatLevel.toUpperCase();

  if (level === "CRITICAL") {
    // Critical Intercept Siren: Dual pulsating tones (880Hz <-> 660Hz)
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sawtooth";

    // Frequency modulation
    osc.frequency.setValueAtTime(880, now);
    osc.frequency.setValueAtTime(660, now + 0.12);
    osc.frequency.setValueAtTime(880, now + 0.24);
    osc.frequency.setValueAtTime(660, now + 0.36);

    // Gain envelope
    gain.gain.setValueAtTime(0.01, now);
    gain.gain.linearRampToValueAtTime(0.2, now + 0.05);
    gain.gain.setValueAtTime(0.2, now + 0.4);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.55);

    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.55);
  } else if (level === "HIGH") {
    // High Priority: Two-tone ascending chime (587Hz -> 880Hz)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(587.33, now); // D5
    gain1.gain.setValueAtTime(0.15, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.2);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.2);

    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(880, now + 0.12); // A5
    gain2.gain.setValueAtTime(0.2, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.38);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.12);
    osc2.stop(now + 0.38);
  } else {
    // Medium / Notice: Single crisp tactical ping (523.25Hz C5)
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(523.25, now);
    gain.gain.setValueAtTime(0.12, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.25);
  }
}
