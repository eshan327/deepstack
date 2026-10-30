import type { PublicEvent } from "./api";

export type TableCue = "card" | "chips" | "check" | "turn" | "win";

export function tableCue(event: PublicEvent, ready: boolean): TableCue | null {
  if (ready && event.view.actor === 0 && !event.view.complete) return "turn";
  if (event.kind === "deal" || event.kind === "board") return "card";
  if (event.kind === "award" && event.view.seats[0]?.winnings > 0) return "win";
  if (event.action === "check") return "check";
  if (["bet", "raise", "call"].includes(event.action || "")) return "chips";
  return null;
}

let context: AudioContext | null = null;
let lastPlayed = -Infinity;

export function unlockTableAudio() {
  try {
    if (typeof AudioContext === "undefined") return;
    context ??= new AudioContext();
    if (context.state === "suspended") void context.resume().catch(() => {});
  } catch {
    // Audio is optional; unavailable devices never interrupt play.
  }
}

export function playTableSound(cue: TableCue) {
  if (!context || context.state !== "running") return;
  const now = context.currentTime;
  if (now - lastPlayed < 0.09) return;
  lastPlayed = now;
  const audio = context;
  function tone(
    frequency: number,
    delay: number,
    length: number,
    volume: number,
  ) {
    const oscillator = audio.createOscillator();
    const envelope = audio.createGain();
    oscillator.frequency.setValueAtTime(frequency, now + delay);
    oscillator.frequency.exponentialRampToValueAtTime(
      frequency * 0.7,
      now + delay + length,
    );
    envelope.gain.setValueAtTime(0, now + delay);
    envelope.gain.linearRampToValueAtTime(volume, now + delay + 0.004);
    envelope.gain.exponentialRampToValueAtTime(0.0001, now + delay + length);
    oscillator.connect(envelope).connect(audio.destination);
    oscillator.start(now + delay);
    oscillator.stop(now + delay + length + 0.01);
    oscillator.onended = () => {
      oscillator.disconnect();
      envelope.disconnect();
    };
  }
  if (cue === "turn" || cue === "win") {
    tone(cue === "turn" ? 660 : 520, 0, 0.16, 0.025);
    tone(cue === "turn" ? 880 : 780, 0.09, 0.2, 0.018);
  } else if (cue === "chips") {
    tone(1900, 0, 0.035, 0.024);
    tone(2400, 0.035, 0.04, 0.012);
  } else if (cue === "check") {
    tone(180, 0, 0.05, 0.04);
  } else {
    const buffer = audio.createBuffer(
      1,
      Math.ceil(audio.sampleRate * 0.065),
      audio.sampleRate,
    );
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++)
      data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
    const source = audio.createBufferSource();
    const filter = audio.createBiquadFilter();
    const envelope = audio.createGain();
    source.buffer = buffer;
    filter.type = "bandpass";
    filter.frequency.value = 2200;
    filter.Q.value = 0.7;
    envelope.gain.value = 0.045;
    source.connect(filter).connect(envelope).connect(audio.destination);
    source.start(now);
    source.onended = () => {
      source.disconnect();
      filter.disconnect();
      envelope.disconnect();
    };
  }
}
