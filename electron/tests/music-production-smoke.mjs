import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { join } from "node:path";
import { withApp } from "./desktop-harness.mjs";

const port = Number(process.env.VOICESTUDIO_MUSIC_SMOKE_PORT);
const output = process.env.VOICESTUDIO_MUSIC_SMOKE_ARTIFACTS;

test(
  "Music Production renders and reopens a real WAV mix and 1080p lyric video",
  {
    skip: !port || !output,
    timeout: 90_000,
  },
  async (t) => {
    mkdirSync(output, { recursive: true });
    const songTitle = "Music Production " + randomUUID().slice(0, 8);
    const base = `http://127.0.0.1:${port}/music/projects`;
    const created = await fetch(base, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: songTitle }),
    });
    assert.equal(created.status, 201);
    const song = await created.json();
    const songUrl = `${base}/${song.id}`;
    const imported = await fetch(songUrl + "/audio", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream", "X-Music-Filename": "tone.wav" },
      body: readFileSync(join(output, "tone.wav")),
    });
    assert.equal(imported.status, 200);
    const lyrics = await fetch(songUrl + "/lyrics", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: randomUUID(),
        text: "[Chorus]\n\u6708\u5149\u843d\u5728\u7a97\u8fb9",
      }),
    });
    assert.equal(lyrics.status, 200);
    await withApp(t, { externalBackendPort: port }, async (session) => {
      async function open(page) {
        await page.getByRole("link", { name: "AI Music", exact: true }).click();
        await page.getByRole("button", { name: new RegExp(songTitle) }).click();
        await page.getByRole("tab", { name: "Production", exact: true }).click();
      }
      await open(session.page);
      await session.page.getByRole("button", { name: "Run workflow", exact: true }).click();
      await session.page.getByRole("link", { name: "production.json", exact: true }).waitFor();
      await session.page.getByRole("link", { name: "mix.wav", exact: true }).waitFor();
      await session.page.getByRole("img", { name: "waveform.png", exact: true }).waitFor();
      const video = session.page.getByLabel("mv.mp4", { exact: true });
      await video.evaluate((element) => {
        element.preload = "metadata";
        element.load();
      });
      await session.page.waitForFunction(() => {
        const clip = document.querySelector('video[aria-label="mv.mp4"]');
        return clip?.videoHeight === 1920 && clip?.videoWidth === 1080;
      });
      await session.page.getByText("Done", { exact: true }).waitFor();
      const run = (await (await fetch(songUrl + "/production")).json())[0];
      assert.deepEqual(run.completed, ["inputs", "stems", "mix", "mv", "export"]);
      const manifest = await (
        await fetch(`${songUrl}/production/${run.id}/files/production.json`)
      ).json();
      writeFileSync(
        join(output, "production-report.json"),
        JSON.stringify(
          {
            completed: run.completed,
            artifactSha256: manifest.artifactSha256,
            inputSha256: manifest.inputSha256,
            analysis: run.analysis,
            videoRenderer: manifest.videoRenderer,
          },
          null,
          2,
        ) + "\n",
      );
      await session.page.screenshot({ path: join(output, "production.png") });
      await session.relaunch();
      await open(session.page);
      await session.page.getByRole("link", { name: "mv.mp4", exact: true }).waitFor();
    });
  },
);
