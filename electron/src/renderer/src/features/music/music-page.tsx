import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Music2Icon, PlusIcon, Trash2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import {
  createSong,
  deleteSong,
  getSong,
  importSongAudio,
  listSongs,
  musicKeys,
  saveLyrics,
  savePrompt,
  saveSong,
  type Song,
} from "./music-api";
import { draftKey, promptFields, songFields, useMusicDraft } from "./music-draft";
import { MusicProduction } from "./music-production";
import { AudioImport, LyricsEditor, SongDetails, SunoEditor } from "./music-editors";
import { musicError, panel, TextField } from "./music-controls";

function SongEditor({ project, onDelete }: { project: Song; onDelete(): void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { draft, patch, clearSaved, storageFailed } = useMusicDraft(project.id);
  const [activity, setActivity] = useState<"saving" | "analyzing" | "saved">();
  const [error, setError] = useState<string>();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const locked = useRef(false);
  const cancelDelete = useRef<HTMLButtonElement>(null);
  const busy = activity === "saving" || activity === "analyzing";
  const dirty = Object.values(draft).some((value) => value !== undefined);
  const lyrics = draft.lyrics?.text ?? project.lyricsVersions.at(-1)?.text ?? "";
  const prompt = draft.prompt?.fields ?? promptFields(project.sunoPrompts.at(-1));
  const fields = draft.details?.fields ?? songFields(project);
  async function run(
    action: () => Promise<Song | void>,
    kind: "saving" | "analyzing",
    finish?: () => void,
  ) {
    if (locked.current) return false;
    locked.current = true;
    setActivity(kind);
    setError(undefined);
    try {
      const saved = await action();
      if (saved) {
        const key = musicKeys.project(project.id);
        await queryClient.cancelQueries({ queryKey: key });
        queryClient.setQueryData<Song>(key, (current) =>
          current && new Date(current.updatedAt) > new Date(saved.updatedAt) ? current : saved,
        );
      }
      void queryClient.invalidateQueries({ queryKey: musicKeys.list });
      finish?.();
      setActivity("saved");
      return true;
    } catch (failure) {
      setError(musicError(failure));
      setActivity(undefined);
      if (failure instanceof ApiError && failure.detail === "project_conflict") {
        void queryClient.invalidateQueries({ queryKey: musicKeys.project(project.id) });
      }
      return false;
    } finally {
      locked.current = false;
    }
  }
  return (
    <section className="min-w-0" aria-label={project.title}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="break-words text-xl font-semibold">{project.title}</h2>
          <p role="status" className="text-sm text-muted-foreground">
            {activity === "analyzing"
              ? t("music.analyzing")
              : busy
                ? t("common.saving")
                : dirty
                  ? t("music.unsaved")
                  : activity === "saved"
                    ? t("music.saved")
                    : t(`music.status.${project.status}`)}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => setConfirmDelete(true)}
        >
          <Trash2Icon aria-hidden="true" />
          {t("common.delete")}
        </Button>
      </header>
      {storageFailed && (
        <p role="alert" className="mb-2 text-destructive">
          {t("music.errors.draft_storage")}
        </p>
      )}
      {!confirmDelete && error && (
        <p role="alert" className="mb-2 text-destructive">
          {t(error)}
        </p>
      )}
      <Tabs defaultValue="details">
        <TabsList variant="line" className="h-auto max-w-full flex-wrap justify-start">
          <TabsTrigger value="details">{t("common.details")}</TabsTrigger>
          <TabsTrigger value="lyrics">{t("music.lyrics")}</TabsTrigger>
          <TabsTrigger value="suno">{t("music.suno")}</TabsTrigger>
          <TabsTrigger value="audio">{t("music.audio")}</TabsTrigger>
          <TabsTrigger value="production">{t("music.production.title")}</TabsTrigger>
        </TabsList>
        <TabsContent value="details">
          <SongDetails
            value={fields}
            busy={busy}
            dirty={!!draft.details}
            conflict={!!draft.details && draft.details.revision !== project.revision}
            onChange={(change) =>
              patch({
                details: {
                  revision: draft.details?.revision ?? project.revision,
                  fields: { ...fields, ...change },
                },
              })
            }
            onReset={() => {
              patch({ details: undefined });
              setError(undefined);
            }}
            onSave={() =>
              void run(
                () => saveSong(project.id, fields, draft.details?.revision ?? project.revision),
                "saving",
                () => clearSaved("details", draft.details),
              )
            }
          />
        </TabsContent>
        <TabsContent value="lyrics" keepMounted>
          <LyricsEditor
            value={lyrics}
            onChange={(value) =>
              patch({
                lyrics:
                  value === (project.lyricsVersions.at(-1)?.text ?? "")
                    ? undefined
                    : { id: crypto.randomUUID(), text: value },
              })
            }
            versions={project.lyricsVersions}
            busy={busy}
            onSave={() => {
              const version = draft.lyrics;
              if (version)
                void run(
                  () => saveLyrics(project.id, version),
                  "saving",
                  () => clearSaved("lyrics", version),
                );
            }}
          />
        </TabsContent>
        <TabsContent value="suno" keepMounted>
          <SunoEditor
            value={prompt}
            lyrics={lyrics}
            versions={project.sunoPrompts}
            busy={busy}
            onChange={(value) => patch({ prompt: { id: crypto.randomUUID(), fields: value } })}
            onSave={() => {
              const version = draft.prompt;
              if (version)
                void run(
                  () => savePrompt(project.id, version),
                  "saving",
                  () => clearSaved("prompt", version),
                );
            }}
          />
        </TabsContent>
        <TabsContent value="audio" keepMounted>
          <AudioImport
            assets={project.audioAssets}
            busy={busy}
            onImport={(file, source, rights) =>
              run(() => importSongAudio(project.id, file, source, rights), "analyzing")
            }
          />
        </TabsContent>
        <TabsContent value="production" keepMounted>
          <MusicProduction project={project} />
        </TabsContent>
      </Tabs>
      <Dialog
        open={confirmDelete}
        onOpenChange={(open) => {
          if (!busy) setConfirmDelete(open);
        }}
      >
        <DialogContent initialFocus={cancelDelete} showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{t("music.delete_project")}</DialogTitle>
            <DialogDescription>
              {t("music.delete_policy", { title: project.title })}
            </DialogDescription>
          </DialogHeader>
          {error && (
            <p role="alert" className="text-destructive">
              {t(error)}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              ref={cancelDelete}
              disabled={busy}
              onClick={() => setConfirmDelete(false)}
            >
              {t("common.cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() =>
                void run(
                  async () => {
                    await deleteSong(project.id);
                    try {
                      localStorage.removeItem(draftKey(project.id));
                    } catch {
                      /* The server deletion succeeded. */
                    }
                  },
                  "saving",
                  onDelete,
                )
              }
            >
              {t("common.delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export function MusicPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [id, setId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string>();
  const songs = useQuery({ queryKey: musicKeys.list, queryFn: ({ signal }) => listSongs(signal) });
  const project = useQuery({
    queryKey: musicKeys.project(id ?? ""),
    queryFn: ({ signal }) => getSong(id!, signal),
    enabled: !!id,
  });
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" });
  return (
    <main
      className="workspace-content h-full overflow-y-auto px-4 py-5 @lg:px-7"
      aria-labelledby="music-page-title"
    >
      <div className="mx-auto grid max-w-6xl gap-5">
        <header className="grid gap-1">
          <h1 id="music-page-title" className="flex items-center gap-2 text-2xl font-semibold">
            <Music2Icon className="size-5" aria-hidden="true" />
            {t("music.title")}
          </h1>
          <p className="max-w-3xl text-sm text-muted-foreground">{t("music.modes")}</p>
        </header>
        <div className="grid min-w-0 gap-5 @3xl:grid-cols-[15rem_minmax(0,1fr)]">
          <aside className={cn(panel, "self-start")}>
            <form
              className="grid gap-2"
              onSubmit={async (event) => {
                event.preventDefault();
                if (creating || !title.trim()) return;
                setCreating(true);
                setCreateError(undefined);
                try {
                  const created = await createSong(title.trim());
                  queryClient.setQueryData(musicKeys.project(created.id), created);
                  setId(created.id);
                  setTitle("");
                  void queryClient.invalidateQueries({ queryKey: musicKeys.list });
                } catch (failure) {
                  setCreateError(musicError(failure));
                } finally {
                  setCreating(false);
                }
              }}
            >
              <TextField
                label={t("music.fields.title")}
                value={title}
                required
                autoComplete="off"
                maxLength={200}
                onChange={(event) => setTitle(event.target.value)}
              />
              <Button type="submit" disabled={!title.trim() || creating}>
                <PlusIcon aria-hidden="true" />
                {creating ? t("common.saving") : t("music.create")}
              </Button>
              {createError && (
                <p role="alert" className="text-sm text-destructive">
                  {t(createError)}
                </p>
              )}
            </form>
            <h2 className="mt-5 mb-2 font-medium">{t("music.projects")}</h2>
            {songs.isPending && (
              <p role="status" className="text-sm">
                {t("common.loading")}
              </p>
            )}
            {songs.isError && (
              <div className="grid gap-2">
                <p role="alert" className="text-sm text-destructive">
                  {t(musicError(songs.error))}
                </p>
                <Button variant="outline" onClick={() => void songs.refetch()}>
                  {t("common.retry")}
                </Button>
              </div>
            )}
            {songs.data?.length === 0 && (
              <p className="text-sm text-muted-foreground">{t("music.no_projects")}</p>
            )}
            <ul className="grid max-h-80 gap-1 overflow-auto">
              {songs.data?.map((song) => (
                <li key={song.id}>
                  <Button
                    variant={id === song.id ? "secondary" : "ghost"}
                    className="h-auto min-w-0 w-full flex-col items-start gap-0.5 py-2 text-start whitespace-normal"
                    aria-pressed={id === song.id}
                    onClick={() => setId(song.id)}
                  >
                    <span className="w-full break-words">{song.title}</span>
                    <span className="text-xs font-normal text-muted-foreground">
                      {t(`music.status.${song.status}`)} · {date.format(new Date(song.updatedAt))}
                    </span>
                  </Button>
                </li>
              ))}
            </ul>
          </aside>
          {id && project.data ? (
            <SongEditor
              key={id}
              project={project.data}
              onDelete={() => {
                setId(null);
                queryClient.removeQueries({ queryKey: musicKeys.project(id) });
              }}
            />
          ) : id && project.isError ? (
            <div className={panel}>
              <p role="alert" className="mb-2 text-destructive">
                {t(musicError(project.error))}
              </p>
              <Button variant="outline" onClick={() => void project.refetch()}>
                {t("common.retry")}
              </Button>
            </div>
          ) : (
            <div className={cn(panel, "self-start text-sm text-muted-foreground")}>
              {id ? (
                <p role="status">{t("common.loading")}</p>
              ) : (
                <ul className="grid list-disc gap-2 ps-5">
                  <li>{t("music.lyrics")}</li>
                  <li>{t("music.suno")}</li>
                  <li>{t("music.audio")}</li>
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
