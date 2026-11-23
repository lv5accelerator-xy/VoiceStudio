# AI Music workspace

Open **AI Music** in the desktop sidebar. Create a song and save its brief in **Details**. Write or paste lyrics and save a version. Select an older lyric version to compare it with the editor text and optionally use it as a new draft. The **Suno prompt** tab stores a separate set of versions and can download the edited prompt as JSON.

Copy the lyrics, English style prompt and exclusions to Suno's official site when you are ready to generate the track. Download your selected take, return to VoiceStudio and import a local WAV or MP3. Select the source and usage-rights status at import. For generated and third-party audio, leave the rights unverified until you have verified the applicable terms yourself.

The audio card reports encoding and container, duration, sample rate, channels, byte size, SHA-256, integrated loudness in LUFS and true peak in dBTP. The latter two are FFmpeg measurements of the input. A silent file may have no finite result. An available decoder with an unavailable analysis filter gives an explicit analysis failure. The workbench does not normalize or alter the audio.

Text drafts are restored when you navigate away and return to a project in the same renderer profile. Use **Save** or **Save version** to put them in the project database. The application keeps up to 100 versions of each kind and 30 audio imports per project. Audio limits are 256 MiB and 20 minutes per file.

## Codex-assisted mode

From the repository, run `python scripts/install_music_skills.py` to install the optional text-only skills into `.agents/skills/`. Run the same command with `--check` to verify the local copies without using the network. Start a new Codex session in the repository and invoke `music-studio-workflow`. Existing local edits to an upstream skill directory are preserved. The installer checks exact Git revisions and per-skill content digests. The installer is a developer action and is never called by VoiceStudio.

| Source | Reviewed revision | License and scope |
| --- | --- | --- |
| [lyric-writing-skills](https://github.com/jtydhr88/lyric-writing-skills/tree/753ee94bdadcf6e0001b3f3262b7aca1cfc485fa/plugins/lyric-writing/skills) | `753ee94bdadcf6e0001b3f3262b7aca1cfc485fa` | MIT for original material, with rights exclusions in its NOTICE. Five selected skills and their adjacent text references install locally. |
| [music-composition-skills](https://github.com/jtydhr88/music-composition-skills/tree/e283141babb8806f2798d5fd2d9e833e75c1bd26/plugins/music-composition/skills) | `e283141babb8806f2798d5fd2d9e833e75c1bd26` | MIT for original material, with rights exclusions in its NOTICE. Five selected skills and their adjacent Markdown/YAML install locally. |
| [remotion-dev/skills](https://github.com/remotion-dev/skills/tree/89c8afa3eee9cdd83838ac31979c2ba1384615aa) | `89c8afa3eee9cdd83838ac31979c2ba1384615aa` | P3 candidate. This snapshot has no top-level license file. Confirm the applicable skill and render-package licensing before installing, redistributing or adding dependencies. |

The first two repositories contain instructional Markdown and data examples in the selected paths. The installer permits Markdown and YAML, copies the upstream LICENSE and NOTICE, and does not execute repository content. Some instructions refer to other skills or original source books. The P1 workflow uses the selected guides and does not require those optional cross-references. Third-party text excerpts stay in the local installation. The VoiceStudio coordinator lives in this fork and uses the project license.

To use results in the manual mode, paste the text or JSON fields into the corresponding editor and save. To save directly from Codex, use the backend on the same machine and write to the intended UUID. The exact OpenAPI schema is generated in `mobile/contract/openapi.json`. Example using the default port:

```bash
curl --fail-with-body http://127.0.0.1:3900/music/projects
curl --fail-with-body -X PUT --json @lyrics-version.json http://127.0.0.1:3900/music/projects/PROJECT_UUID/lyrics
curl --fail-with-body -X PUT --json @suno-prompt-version.json http://127.0.0.1:3900/music/projects/PROJECT_UUID/suno-prompts
```

On Windows PowerShell use `curl.exe` and quote each `@filename` argument. Use the backend's configured port if it differs. A lyrics request contains `{"id":"VERSION_UUID","text":"[Chorus]\\n…"}`. A prompt request contains a fresh version UUID and `stylePrompt`, with optional `style`, `mood`, `rhythm`, `instruments`, `vocal`, `arrangement`, `exclusions` and `explanation`. Use a different UUID for each version and the same UUID to retry that version. VoiceStudio itself has no model invocation for this workflow.

## API and data retention

The desktop transport sends calls to `/api/music/projects` and the backend exposes `/music/projects`. The router uses the existing administrator gate and the app's standard origin and credential middleware.

| Endpoint shape | Result |
| --- | --- |
| `GET /music/projects` | Song summaries ordered by most recent save. |
| `POST /music/projects` | Creates a song using the supplied brief and defaults. |
| `GET /music/projects/{id}` | Full schema-versioned song, immutable lyrics and prompt versions, and audio analysis records. |
| `PUT /music/projects/{id}` | Replaces the editable brief using its current metadata revision. A stale change returns 409. |
| `PUT /music/projects/{id}/lyrics`, `…/suno-prompts` | Appends a version. A retry of the same version is idempotent. |
| `POST /music/projects/{id}/audio` | Streams `application/octet-stream`, with UTF-8 percent-encoded filename in `X-Music-Filename`. Optional `source` and `rights` query fields default to `unknown` and `unverified`. Audio is measured before the final project update is committed. |
| `DELETE /music/projects/{id}` | Deletes the project record, text versions and analysis. Returns `retainedAudio: true`. The Electron dialog asks for explicit confirmation. |

Projects live in a new `music_projects` table in the existing SQLite database. The Alembic migration is additive. Imported originals live at `<VoiceStudio data>/music/originals/<project UUID>/<SHA-256>.<extension>`. The displayed original filename is metadata. A repeat import of the same bytes retains the first source/rights metadata and can refresh a previously unsuccessful analysis. Deleting a project preserves both the source file and the workbench's copy. Keep an independent backup of these audio files if you need them.

Uploads stream to `music/staging` in the same data directory. FFmpeg and FFprobe accept local input protocols only and probe the specified WAV/MP3 demuxer. Failed requests clean up staging. Abrupt termination can leave a staged file or an unreferenced complete original. Such files are never returned as imported assets. Reimporting the same file recovers the same content-addressed location. A staging file left by a terminated process can be removed while VoiceStudio is stopped.

See [future integration contracts](ROADMAP.md) for P2–P4 and [verification](VERIFICATION.md) for runtime evidence.
