import { apiJson } from "@/lib/api/client";

export const statuses = [
  "draft",
  "writing",
  "ready_for_suno",
  "audio_imported",
  "complete",
] as const;
export const sources = ["unknown", "suno", "original", "third_party"] as const;
export const rightsOptions = ["unverified", "personal_use", "commercial_confirmed"] as const;

export type SongStatus = (typeof statuses)[number];
export type AudioSource = (typeof sources)[number];
export type Rights = (typeof rightsOptions)[number];

export interface SongFields {
  title: string;
  language: string;
  genre: string;
  theme: string;
  status: SongStatus;
  mood: string;
  vocalType: string;
  bpm: number | null;
  targetSeconds: number | null;
}

export interface PromptFields {
  style: string;
  mood: string;
  rhythm: string;
  instruments: string;
  vocal: string;
  arrangement: string;
  exclusions: string;
  stylePrompt: string;
  explanation: string;
}

interface Version {
  id: string;
  createdAt: string;
}

export interface LyricsVersion extends Version {
  text: string;
}

export interface PromptVersion extends PromptFields, Version {}

export interface AudioAsset extends Version {
  name: string;
  fileType: "wav" | "mp3";
  codec: string;
  durationSeconds: number;
  sampleRateHz: number;
  channels: number;
  sizeBytes: number;
  sha256: string;
  source: AudioSource;
  rights: Rights;
  analysis: {
    status: "complete" | "failed" | "unavailable";
    integratedLufs: number | null;
    truePeakDbtp: number | null;
    error: "no_loudness_result" | "analysis_failed" | null;
  };
}

export interface SongSummary {
  id: string;
  title: string;
  status: SongStatus;
  updatedAt: string;
}

export interface Song extends SongFields, SongSummary {
  schemaVersion: 1;
  revision: number;
  lyricsVersions: LyricsVersion[];
  sunoPrompts: PromptVersion[];
  audioAssets: AudioAsset[];
  createdAt: string;
}

const base = "/music/projects";
const path = (id: string) => `${base}/${encodeURIComponent(id)}`;
const put = (body: object) => ({ method: "PUT", body: JSON.stringify(body) });
export const musicKeys = {
  list: ["music", "projects"] as const,
  project: (id: string) => ["music", "project", id] as const,
};
export const listSongs = (signal: AbortSignal) => apiJson<SongSummary[]>(base, { signal });
export const getSong = (id: string, signal: AbortSignal) => apiJson<Song>(path(id), { signal });
export const createSong = (title: string) =>
  apiJson<Song>(base, { method: "POST", body: JSON.stringify({ title }) });
export const saveSong = (id: string, fields: SongFields, revision: number) =>
  apiJson<Song>(path(id), put({ ...fields, revision }));
export const saveLyrics = (id: string, version: { id: string; text: string }) =>
  apiJson<Song>(`${path(id)}/lyrics`, put(version));
export const savePrompt = (id: string, version: { id: string; fields: PromptFields }) =>
  apiJson<Song>(`${path(id)}/suno-prompts`, put({ id: version.id, ...version.fields }));
export const deleteSong = (id: string) =>
  apiJson<{ retainedAudio: true }>(path(id), { method: "DELETE" });
export const importSongAudio = (id: string, file: File, source: AudioSource, rights: Rights) =>
  apiJson<Song>(`${path(id)}/audio?${new URLSearchParams({ source, rights })}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/octet-stream",
      "X-Music-Filename": encodeURIComponent(file.name),
    },
    body: file,
  });
