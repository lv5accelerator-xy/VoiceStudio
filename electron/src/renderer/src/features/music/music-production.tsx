import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiJson, apiPath, ApiError } from "@/lib/api/client";
import { fieldGrid, LabeledArea, OptionsField, panel, TextField } from "./music-controls";
import type { Song } from "./music-api";

const modes = ["none", "two", "four"] as const;
type Mode = (typeof modes)[number];
const stemNames = {
  none: ["source"],
  two: ["vocals", "accompaniment"],
  four: ["vocals", "drums", "bass", "other"],
} as const;

interface Track {
  stem: string;
  gain: number;
  bass: number;
  treble: number;
  mute: boolean;
  solo: boolean;
  compress: boolean;
}
const trackDefaults = (stem: string): Track => ({
  stem,
  gain: 0,
  bass: 0,
  treble: 0,
  mute: false,
  solo: false,
  compress: false,
});
interface Run {
  id: string;
  state: string;
  error: string | null;
  completed: string[];
  artifacts: string[];
  analysis: { integratedLufs: number | null; truePeakDbtp: number | null } | null;
}

export function MusicProduction({ project }: { project: Song }) {
  const { t } = useTranslation();
  const path = `/music/projects/${project.id}`;
  const [input, setInput] = useState(project.audioAssets.at(-1)?.id ?? "");
  const [lyrics, setLyrics] = useState(project.lyricsVersions.at(-1)?.id ?? "");
  const [mode, setMode] = useState<Mode>("none");
  const [tracks, setTracks] = useState<Record<string, Track>>({});
  const [aspect, setAspect] = useState<"portrait" | "landscape">("portrait");
  const [video, setVideo] = useState<File>();
  const [videoId, setVideoId] = useState<string>();
  const [videoPrompt, setVideoPrompt] = useState("");
  const [storyboard, setStoryboard] = useState("");
  const [bpm, setBpm] = useState(project.bpm ?? 96);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState("");
  const runs = useQuery({
    queryKey: ["music-production", project.id],
    queryFn: ({ signal }) => apiJson<Run[]>(path + "/production", { signal }),
    refetchInterval: (query) =>
      query.state.data?.some((run) => ["pending", "running"].includes(run.state)) ? 800 : false,
    enabled: project.audioAssets.length > 0,
  });
  const capabilities = useQuery({
    queryKey: ["music-production-capabilities", project.id],
    queryFn: ({ signal }) =>
      apiJson<{ videoProvider: boolean }>(path + "/production/capabilities", { signal }),
    enabled: project.audioAssets.length > 0,
  });
  const active = runs.data?.some((run) => ["pending", "running"].includes(run.state));
  const selected = input || project.audioAssets.at(-1)?.id;
  const locked = busy || active;
  const workingTracks = stemNames[mode].map((stem) => tracks[stem] ?? trackDefaults(stem));
  const action = async (operation: () => Promise<unknown>) => {
    setBusy(true);
    setFailure("");
    try {
      await operation();
      await runs.refetch();
    } catch (error) {
      setFailure(
        error instanceof ApiError &&
          ["demucs_weights_missing", "demucs_weights_invalid"].includes(error.detail)
          ? "music.production.weights"
          : error instanceof SyntaxError || (error instanceof ApiError && error.status === 422)
            ? "music.errors.invalid_fields"
            : "music.errors.request_failed",
      );
    } finally {
      setBusy(false);
    }
  };
  const start = (renderVideo: boolean) =>
    action(async () => {
      const cues: unknown = renderVideo && storyboard.trim() ? JSON.parse(storyboard) : [];
      const useProvider = renderVideo && capabilities.data?.videoProvider && videoPrompt.trim();
      let background = renderVideo && !useProvider ? videoId : undefined;
      if (video && renderVideo && !background && !useProvider) {
        const saved = await apiJson<{ id: string }>(path + "/video", {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: video,
        });
        background = saved.id;
        setVideoId(saved.id);
      }
      await apiJson(path + "/production", {
        method: "POST",
        body: JSON.stringify({
          audioId: selected,
          lyricsId: lyrics || null,
          promptId: project.sunoPrompts.at(-1)?.id,
          videoId: background,
          videoPrompt: useProvider || undefined,
          separation: mode,
          tracks: workingTracks,
          aspect,
          renderVideo,
          bpm,
          storyboard: cues,
        }),
      });
    });
  if (!project.audioAssets.length) return <p className={panel}>{t("compare.no_audio")}</p>;

  return (
    <div className="grid gap-3">
      <section className={`${panel} grid gap-3`}>
        <fieldset disabled={locked} className={fieldGrid}>
          <OptionsField
            label={t("music.fields.source")}
            value={selected ?? ""}
            onChange={setInput}
            disabled={locked}
            options={project.audioAssets.map((asset) => ({ value: asset.id, label: asset.name }))}
          />
          <OptionsField
            label={t("music.lyrics_history")}
            value={lyrics}
            onChange={setLyrics}
            disabled={locked}
            options={[
              { value: "", label: t("common.not_set") },
              ...project.lyricsVersions.map((version, i) => ({
                value: version.id,
                label: t("music.version", { number: i + 1 }),
              })),
            ]}
          />
          <OptionsField<Mode>
            label={t("music.production.stems")}
            value={mode}
            onChange={setMode}
            disabled={locked}
            options={modes.map((value) => ({ value, label: t(`music.production.${value}`) }))}
          />
          <OptionsField<"portrait" | "landscape">
            label={t("videoExport.title")}
            value={aspect}
            onChange={setAspect}
            disabled={locked}
            options={[
              { value: "portrait", label: "9:16 · 1080p" },
              { value: "landscape", label: "16:9 · 1080p" },
            ]}
          />
          <TextField
            type="number"
            label={t("music.fields.bpm")}
            min={20}
            max={300}
            value={bpm}
            onChange={(event) => setBpm(event.target.valueAsNumber)}
          />
          <TextField
            type="file"
            accept=".mp4"
            disabled={!!videoPrompt.trim()}
            label={t("music.production.video")}
            onChange={(event) => {
              setVideo(event.target.files?.[0]);
              setVideoId(undefined);
            }}
          />
        </fieldset>
        {capabilities.data?.videoProvider && (
          <TextField
            label={`${t("music.production.video")} · ${t("music.fields.stylePrompt")}`}
            value={videoPrompt}
            maxLength={2000}
            disabled={locked || !!video}
            onChange={(event) => setVideoPrompt(event.target.value)}
          />
        )}
        <LabeledArea label={t("music.production.storyboard")}>
          {(id) => (
            <Textarea
              id={id}
              disabled={locked}
              value={storyboard}
              placeholder={'[{"startMs":0,"endMs":1000,"text":"…"}]'}
              onChange={(event) => setStoryboard(event.target.value)}
            />
          )}
        </LabeledArea>
        {workingTracks.map((track) => {
          const update = (change: Partial<Track>) =>
            setTracks((current) => ({ ...current, [track.stem]: { ...track, ...change } }));
          return (
            <fieldset
              key={track.stem}
              disabled={locked}
              className={`${fieldGrid} rounded border p-2`}
            >
              <legend>{t(`music.production.${track.stem}`)}</legend>
              {(["gain", "bass", "treble"] as const).map((key) => (
                <TextField
                  key={key}
                  label={t(`music.production.${key}`)}
                  value={track[key]}
                  type="number"
                  min={key === "gain" ? -60 : -15}
                  max={key === "gain" ? 12 : 15}
                  step={0.1}
                  onChange={(event) => update({ [key]: event.target.valueAsNumber || 0 })}
                />
              ))}
              <div className="flex flex-wrap gap-3">
                {(["mute", "solo", "compress"] as const).map((key) => (
                  <label className="flex gap-1.5" key={key}>
                    <input
                      type="checkbox"
                      checked={track[key]}
                      onChange={(event) => update({ [key]: event.target.checked })}
                    />
                    {t(key === "mute" ? "player.mute" : `music.production.${key}`)}
                  </label>
                ))}
              </div>
            </fieldset>
          );
        })}
        <div className="flex flex-wrap gap-2">
          <Button disabled={locked || !selected} onClick={() => void start(false)}>
            {t("music.production.mix")}
          </Button>
          <Button disabled={locked || !selected} variant="outline" onClick={() => void start(true)}>
            {t("workflowRun.run")}
          </Button>
        </div>
        {failure && (
          <p role="alert" className="text-destructive">
            {t(failure)}
          </p>
        )}
        {runs.isError && (
          <p role="alert" className="text-destructive">
            {t("music.errors.request_failed")}
          </p>
        )}
      </section>
      {runs.data?.map((run) => (
        <section key={run.id} className={`${panel} grid gap-2`}>
          <div className="flex flex-wrap gap-2">
            <strong role="status">{t(`music.production.${run.state}`)}</strong>
            {run.completed.map((stage) => (
              <span key={stage} className="text-muted-foreground">
                {t(`music.production.${stage}`)}
              </span>
            ))}
          </div>
          {run.error && (
            <p role="alert" className="text-destructive">
              {t("music.errors.request_failed")}
            </p>
          )}
          {run.analysis && (
            <p>
              {run.analysis.integratedLufs ?? "—"} LUFS · {run.analysis.truePeakDbtp ?? "—"} dBTP
            </p>
          )}
          {run.artifacts.map((name) => {
            const url = apiPath(`${path}/production/${run.id}/files/${name}`);
            return (
              <div key={name} className="grid min-w-0 gap-1">
                <a className="text-primary underline" href={url} download={name}>
                  {name}
                </a>
                {name.endsWith(".wav") && (
                  <audio className="w-full" aria-label={name} controls preload="none" src={url} />
                )}
                {name === "waveform.png" && <img className="w-full" src={url} alt={name} />}
                {name.endsWith(".mp4") && (
                  <video
                    className="max-h-96 max-w-full"
                    aria-label={name}
                    controls
                    preload="none"
                    src={url}
                  />
                )}
              </div>
            );
          })}
          {["pending", "running"].includes(run.state) && (
            <Button
              disabled={busy}
              variant="outline"
              onClick={() =>
                void action(() =>
                  apiJson(`${path}/production/${run.id}/cancel`, { method: "POST" }),
                )
              }
            >
              {t("common.cancel")}
            </Button>
          )}
          {["failed", "cancelled"].includes(run.state) && (
            <Button
              disabled={locked}
              variant="outline"
              onClick={() =>
                void action(() => apiJson(`${path}/production/${run.id}/retry`, { method: "POST" }))
              }
            >
              {t("common.retry")}
            </Button>
          )}
          {["done", "failed", "cancelled"].includes(run.state) && (
            <Button
              disabled={busy}
              variant="ghost"
              onClick={() =>
                void action(() =>
                  apiJson(`${path}/production/${run.id}`, { method: "DELETE" }),
                )
              }
            >
              {t("common.delete")}
            </Button>
          )}
        </section>
      ))}
    </div>
  );
}
