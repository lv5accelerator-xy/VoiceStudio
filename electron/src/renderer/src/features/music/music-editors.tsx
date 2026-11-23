import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DownloadIcon, FileMusicIcon, SaveIcon } from "lucide-react";
import { ExternalLink } from "@/components/external-link";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  statuses,
  sources,
  rightsOptions,
  type AudioAsset,
  type AudioSource,
  type LyricsVersion,
  type PromptFields,
  type PromptVersion,
  type Rights,
  type SongFields,
} from "./music-api";
import { promptFields } from "./music-draft";
import {
  CopyButton,
  fieldGrid,
  LabeledArea,
  OptionsField,
  panel,
  TextField,
} from "./music-controls";

const tags = [
  "Intro",
  "Verse 1",
  "Pre-Chorus",
  "Chorus",
  "Verse 2",
  "Bridge",
  "Final Chorus",
  "Outro",
];
const briefFields = ["title", "language", "theme", "genre", "mood", "vocalType"] as const;
const promptTextFields = [
  "style",
  "mood",
  "rhythm",
  "instruments",
  "vocal",
  "arrangement",
] as const;
const promptAreas = ["stylePrompt", "exclusions", "explanation"] as const;
const MAX_AUDIO_BYTES = 256 * 1024 * 1024;

export function SongDetails({
  value,
  onChange,
  onSave,
  onReset,
  dirty,
  busy,
  conflict,
}: {
  value: SongFields;
  onChange(fields: Partial<SongFields>): void;
  onSave(): void;
  onReset(): void;
  dirty: boolean;
  busy: boolean;
  conflict: boolean;
}) {
  const { t } = useTranslation();
  return (
    <form
      className={panel}
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      <fieldset disabled={busy} className={fieldGrid}>
        {briefFields.map((field) => (
          <TextField
            key={field}
            label={t(`music.fields.${field}`)}
            value={value[field]}
            required={field === "title" || field === "language"}
            maxLength={field === "title" ? 200 : field === "language" ? 40 : 500}
            onChange={(event) => onChange({ [field]: event.target.value })}
          />
        ))}
        <TextField
          label={t("music.fields.bpm")}
          type="number"
          min={20}
          max={300}
          value={value.bpm ?? ""}
          onChange={(event) => onChange({ bpm: event.target.valueAsNumber || null })}
        />
        <TextField
          label={t("music.fields.targetSeconds")}
          type="number"
          min={1}
          max={1200}
          value={value.targetSeconds ?? ""}
          onChange={(event) => onChange({ targetSeconds: event.target.valueAsNumber || null })}
        />
        <OptionsField
          label={t("music.fields.status")}
          value={value.status}
          disabled={busy}
          options={statuses.map((status) => ({
            value: status,
            label: t(`music.status.${status}`),
          }))}
          onChange={(status) => onChange({ status })}
        />
      </fieldset>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!dirty || busy || conflict}>
          <SaveIcon aria-hidden="true" />
          {t("common.save")}
        </Button>
        {conflict && (
          <>
            <p role="alert" className="text-sm text-destructive">
              {t("music.errors.project_conflict")}
            </p>
            <Button type="button" variant="outline" onClick={onReset} disabled={busy}>
              {t("music.use_saved_details")}
            </Button>
          </>
        )}
      </div>
    </form>
  );
}

function VersionHistory({
  versions,
  current,
  onSelect,
  busy,
  title,
}: {
  versions: { id: string; createdAt: string }[];
  current: string | undefined;
  onSelect(id: string): void;
  busy: boolean;
  title: string;
}) {
  const { t, i18n } = useTranslation();
  const format = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "short",
    timeStyle: "short",
  });
  return (
    <section aria-label={title} className={panel}>
      <h3 className="mb-2 font-medium">{title}</h3>
      {versions.length === 0 ? (
        <p className="text-muted-foreground">{t("music.no_versions")}</p>
      ) : (
        <ol className="grid max-h-48 gap-1 overflow-auto">
          {[...versions].reverse().map((version, index) => (
            <li key={version.id}>
              <Button
                type="button"
                variant={current === version.id ? "secondary" : "ghost"}
                aria-pressed={current === version.id}
                disabled={busy}
                className="justify-start whitespace-normal"
                onClick={() => onSelect(version.id)}
              >
                {t("music.version", { number: versions.length - index })}
                <time dateTime={version.createdAt} className="font-normal text-muted-foreground">
                  {format.format(new Date(version.createdAt))}
                </time>
              </Button>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function LyricsEditor({
  value,
  onChange,
  versions,
  onSave,
  busy,
}: {
  value: string;
  onChange(value: string): void;
  versions: LyricsVersion[];
  onSave(): void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  const editor = useRef<HTMLTextAreaElement>(null);
  const [selected, setSelected] = useState<string>();
  const version = versions.find((entry) => entry.id === selected);
  function insert(tag: string) {
    const element = editor.current;
    if (!element) return;
    const start = element.selectionStart;
    const prefix = value.slice(0, start);
    const insertion = `${prefix.endsWith("\n") || !prefix ? "" : "\n"}[${tag}]\n`;
    const next = prefix + insertion + value.slice(element.selectionEnd);
    if (next.length > 24000) return;
    onChange(next);
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(start + insertion.length, start + insertion.length);
    });
  }
  return (
    <div className="grid gap-4">
      <section className={panel}>
        <div
          className="mb-3 flex flex-wrap gap-1"
          aria-label={t("music.section_tags")}
          role="group"
        >
          {tags.map((tag) => (
            <Button
              key={tag}
              type="button"
              variant="secondary"
              size="xs"
              disabled={busy}
              onClick={() => insert(tag)}
            >
              [{tag}]
            </Button>
          ))}
        </div>
        <div className={version ? fieldGrid : ""}>
          <LabeledArea label={t("music.lyrics_text")}>
            {(id) => (
              <Textarea
                id={id}
                ref={editor}
                value={value}
                disabled={busy}
                maxLength={24000}
                className="min-h-64 font-mono"
                onChange={(event) => onChange(event.target.value)}
              />
            )}
          </LabeledArea>
          {version && (
            <LabeledArea label={t("music.comparison")}>
              {(id) => (
                <Textarea id={id} readOnly value={version.text} className="min-h-64 font-mono" />
              )}
            </LabeledArea>
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            onClick={onSave}
            disabled={busy || !value.trim() || value.trim() === versions.at(-1)?.text}
          >
            {t("music.save_version")}
          </Button>
          <CopyButton value={value}>{t("music.copy_lyrics")}</CopyButton>
          {version && (
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => onChange(version.text)}
            >
              {t("music.use_version")}
            </Button>
          )}
        </div>
      </section>
      <VersionHistory
        title={t("music.lyrics_history")}
        versions={versions}
        current={selected}
        onSelect={setSelected}
        busy={busy}
      />
    </div>
  );
}

function downloadPrompt(value: PromptFields) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2) + "\n"], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "suno-prompt.json";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function SunoEditor({
  value,
  lyrics,
  versions,
  onChange,
  onSave,
  busy,
}: {
  value: PromptFields;
  lyrics: string;
  versions: PromptVersion[];
  onChange(fields: PromptFields): void;
  onSave(): void;
  busy: boolean;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<string>();
  const selectedVersion = versions.find((entry) => entry.id === selected);
  const latest = versions.at(-1);
  const changed = Object.keys(value).some(
    (field) => value[field as keyof PromptFields] !== latest?.[field as keyof PromptFields],
  );
  return (
    <div className="grid gap-4">
      <section className={panel}>
        <p className="mb-4 text-muted-foreground">{t("music.suno_help")}</p>
        <fieldset disabled={busy} className={fieldGrid}>
          {promptTextFields.map((field) => (
            <TextField
              key={field}
              label={t(`music.fields.${field}`)}
              value={value[field]}
              maxLength={500}
              onChange={(event) => onChange({ ...value, [field]: event.target.value })}
            />
          ))}
        </fieldset>
        <div className="mt-4 grid gap-3">
          {promptAreas.map((field) => (
            <LabeledArea key={field} label={t(`music.fields.${field}`)}>
              {(id) => (
                <Textarea
                  id={id}
                  value={value[field]}
                  disabled={busy}
                  maxLength={4000}
                  onChange={(event) => onChange({ ...value, [field]: event.target.value })}
                />
              )}
            </LabeledArea>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            type="button"
            onClick={onSave}
            disabled={busy || !value.stylePrompt.trim() || !changed}
          >
            {t("music.save_version")}
          </Button>
          <CopyButton value={lyrics}>{t("music.copy_lyrics")}</CopyButton>
          <CopyButton value={value.stylePrompt}>{t("music.copy_prompt")}</CopyButton>
          <CopyButton value={value.exclusions}>{t("music.copy_exclusions")}</CopyButton>
          <Button
            type="button"
            variant="outline"
            disabled={!value.stylePrompt.trim()}
            onClick={() => downloadPrompt(value)}
          >
            <DownloadIcon aria-hidden="true" />
            {t("music.export_prompt")}
          </Button>
          <ExternalLink href="https://suno.com">{t("music.open_suno")}</ExternalLink>
        </div>
      </section>
      <VersionHistory
        title={t("music.prompt_history")}
        versions={versions}
        current={selected}
        onSelect={setSelected}
        busy={busy}
      />
      {selectedVersion && (
        <section className={panel}>
          <h3 className="mb-2 font-medium">{t("music.fields.stylePrompt")}</h3>
          <p className="mb-3 whitespace-pre-wrap break-words">{selectedVersion.stylePrompt}</p>
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => onChange(promptFields(selectedVersion))}
          >
            {t("music.use_version")}
          </Button>
        </section>
      )}
    </div>
  );
}

function AudioReport({ asset }: { asset: AudioAsset }) {
  const { t, i18n } = useTranslation();
  const count = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  const number = (value: number | null, unit: string) =>
    value === null ? t("common.not_set") : `${count.format(value)} ${unit}`;
  const metrics = [
    [t("music.fields.format"), `${asset.fileType.toUpperCase()} · ${asset.codec}`],
    [t("music.fields.duration"), number(asset.durationSeconds, "s")],
    [t("music.fields.sample_rate"), number(asset.sampleRateHz, "Hz")],
    [t("music.fields.channels"), count.format(asset.channels)],
    [t("music.fields.size"), `${count.format(asset.sizeBytes)} B`],
    [t("music.fields.source"), t(`music.source.${asset.source}`)],
    [t("music.fields.rights"), t(`music.rights.${asset.rights}`)],
    [t("music.fields.analysis"), t(`music.analysis.${asset.analysis.status}`)],
    [t("music.fields.integrated"), number(asset.analysis.integratedLufs, "LUFS")],
    [t("music.fields.peak"), number(asset.analysis.truePeakDbtp, "dBTP")],
  ];
  return (
    <article className={panel}>
      <h3 className="mb-3 flex items-start gap-2 font-medium">
        <FileMusicIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 break-words">{asset.name}</span>
      </h3>
      <dl className="grid min-w-0 grid-cols-2 gap-3 @xl:grid-cols-3">
        {metrics.map(([label, value], index) => (
          <div key={index} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="break-words">{value}</dd>
          </div>
        ))}
        <div className="col-span-full min-w-0">
          <dt className="text-xs text-muted-foreground">SHA-256</dt>
          <dd className="break-all font-mono text-xs" dir="ltr">
            {asset.sha256}
          </dd>
        </div>
      </dl>
      {asset.analysis.error && (
        <p className="mt-3 text-sm text-muted-foreground">
          {t(`music.analysis.${asset.analysis.error}`)}
        </p>
      )}
    </article>
  );
}

export function AudioImport({
  assets,
  busy,
  onImport,
}: {
  assets: AudioAsset[];
  busy: boolean;
  onImport(file: File, source: AudioSource, rights: Rights): Promise<boolean>;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File>();
  const [source, setSource] = useState<AudioSource>("unknown");
  const [rights, setRights] = useState<Rights>("unverified");
  const tooLarge = !!file && file.size > MAX_AUDIO_BYTES;
  return (
    <div className="grid gap-3">
      <form
        className={panel}
        onSubmit={async (event) => {
          event.preventDefault();
          if (!file || tooLarge || busy) return;
          if (await onImport(file, source, rights)) {
            setFile(undefined);
            if (input.current) input.current.value = "";
          }
        }}
      >
        <p className="mb-3 text-muted-foreground">{t("music.audio_help")}</p>
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <input
            hidden
            type="file"
            ref={input}
            accept=".wav,.mp3"
            disabled={busy}
            aria-label={t("music.choose_audio")}
            onChange={(event) => setFile(event.target.files?.[0])}
          />
          <Button
            type="button"
            variant="outline"
            disabled={busy}
            onClick={() => input.current?.click()}
          >
            {t("music.choose_audio")}
          </Button>
          <span className="min-w-0 break-words text-muted-foreground" aria-live="polite">
            {file?.name ?? t("common.not_set")}
          </span>
        </div>
        <fieldset className={`mt-3 ${fieldGrid}`} disabled={busy}>
          <OptionsField<AudioSource>
            label={t("music.fields.source")}
            value={source}
            onChange={setSource}
            disabled={busy}
            options={sources.map((value) => ({ value, label: t(`music.source.${value}`) }))}
          />
          <OptionsField<Rights>
            label={t("music.fields.rights")}
            value={rights}
            onChange={setRights}
            disabled={busy}
            options={rightsOptions.map((value) => ({ value, label: t(`music.rights.${value}`) }))}
          />
        </fieldset>
        {tooLarge && (
          <p role="alert" className="mt-2 text-destructive">
            {t("music.errors.file_too_large")}
          </p>
        )}
        <Button type="submit" className="mt-3" disabled={!file || tooLarge || busy}>
          {t("music.import_audio")}
        </Button>
      </form>
      {[...assets].reverse().map((asset) => (
        <AudioReport key={asset.id} asset={asset} />
      ))}
    </div>
  );
}
