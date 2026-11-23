import { useId, type ComponentProps, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
// @ts-expect-error shared JSX component has no declaration file
import SearchableSelect from "@shared/components/SearchableSelect";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { toast } from "sonner";

export const fieldGrid = "grid min-w-0 gap-4 sm:grid-cols-2";
export const panel = "min-w-0 rounded-lg border border-border bg-card p-4";

export function TextField({ label, ...props }: ComponentProps<typeof Input> & { label: string }) {
  return (
    <label className="grid min-w-0 gap-1.5 text-sm font-medium">
      {label}
      <Input {...props} />
    </label>
  );
}

export function OptionsField<T extends string>({
  label,
  options,
  value,
  onChange,
  disabled,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange(value: T): void;
  disabled?: boolean;
}) {
  return (
    <div className="grid min-w-0 gap-1.5 text-sm font-medium">
      <span>{label}</span>
      <SearchableSelect
        ariaLabel={label}
        options={options}
        value={value}
        onChange={onChange}
        disabled={disabled}
        menuPortal
        buttonClassName="flex h-8 w-full items-center justify-between rounded-md border border-input bg-input/20 px-2 text-sm"
      />
    </div>
  );
}

export function LabeledArea({
  label,
  children,
}: {
  label: string;
  children(id: string): ReactNode;
}) {
  const id = useId();
  return (
    <div className="grid min-w-0 gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

export function CopyButton({ value, children }: { value: string; children: ReactNode }) {
  const { t } = useTranslation();
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(t("music.copied"));
    } catch {
      toast.error(t("music.copy_failed"));
    }
  }
  return (
    <Button type="button" variant="outline" disabled={!value.trim()} onClick={() => void copy()}>
      {children}
    </Button>
  );
}

const errors = {
  project_missing: "music.errors.project_missing",
  project_conflict: "music.errors.project_conflict",
  version_conflict: "music.errors.project_conflict",
  version_limit: "music.errors.version_limit",
  asset_limit: "music.errors.asset_limit",
  prompt_required: "music.errors.invalid_fields",
  unsafe_filename: "music.errors.unsafe_filename",
  unsupported_format: "music.errors.unsupported_format",
  invalid_audio: "music.errors.invalid_audio",
  probe_failed: "music.errors.invalid_audio",
  media_tools_missing: "music.errors.media_tools_missing",
  file_too_large: "music.errors.file_too_large",
  analysis_timeout: "music.errors.analysis_timeout",
  unsafe_storage: "music.errors.storage_failed",
  storage_failed: "music.errors.storage_failed",
} as const;

export function musicError(error: unknown): string {
  if (error instanceof ApiError) {
    if (Object.hasOwn(errors, error.detail)) return errors[error.detail as keyof typeof errors];
    if (error.status === 422) return "music.errors.invalid_fields";
    if (error.status === 401 || error.status === 403) return "music.errors.access";
  }
  return "music.errors.request_failed";
}
