import { useRef, useState } from "react";
import type { PromptFields, Song, SongFields } from "./music-api";

export function promptFields(prompt?: PromptFields): PromptFields {
  return {
    style: prompt?.style ?? "",
    mood: prompt?.mood ?? "",
    rhythm: prompt?.rhythm ?? "",
    instruments: prompt?.instruments ?? "",
    vocal: prompt?.vocal ?? "",
    arrangement: prompt?.arrangement ?? "",
    exclusions: prompt?.exclusions ?? "",
    stylePrompt: prompt?.stylePrompt ?? "",
    explanation: prompt?.explanation ?? "",
  };
}

export function songFields(song: Song): SongFields {
  const { title, language, genre, theme, status, mood, vocalType, bpm, targetSeconds } = song;
  return { title, language, genre, theme, status, mood, vocalType, bpm, targetSeconds };
}

interface Draft {
  details?: { revision: number; fields: SongFields };
  lyrics?: { id: string; text: string };
  prompt?: { id: string; fields: PromptFields };
}

export function draftKey(id: string) {
  return `voicestudio.music.draft.v1.${id}`;
}

function storedDraft(key: string): Draft | undefined {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "{}") ?? {};
  } catch {
    return undefined;
  }
}

export function useMusicDraft(id: string) {
  const key = draftKey(id);
  const [draft, setDraft] = useState<Draft>(() => storedDraft(key) ?? {});
  const [storageFailed, setStorageFailed] = useState(false);
  const lastDraft = useRef(draft);
  const unavailable = useRef(false);
  const read = () => (unavailable.current ? undefined : storedDraft(key)) ?? lastDraft.current;
  const write = (next: Draft) => {
    lastDraft.current = next;
    setDraft(next);
    try {
      if (Object.values(next).some((value) => value !== undefined)) {
        localStorage.setItem(key, JSON.stringify(next));
      } else {
        localStorage.removeItem(key);
      }
      unavailable.current = false;
    } catch {
      unavailable.current = true;
    }
    setStorageFailed(unavailable.current);
  };
  const patch = (fields: Partial<Draft>) => write({ ...read(), ...fields });
  const clearSaved = <K extends keyof Draft>(section: K, expected: Draft[K]) => {
    const latest = read();
    // A prior editor may finish saving after the same song is reopened.
    // Never clear a draft that was edited after that request started.
    if (JSON.stringify(latest[section]) === JSON.stringify(expected)) {
      write({ ...latest, [section]: undefined });
    }
  };
  return { draft, patch, clearSaved, storageFailed };
}
