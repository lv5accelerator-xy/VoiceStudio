import { test } from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { withApp } from "./desktop-harness.mjs";

const backend = Number(process.env.VOICESTUDIO_MUSIC_SMOKE_PORT);
const output = process.env.VOICESTUDIO_MUSIC_SMOKE_ARTIFACTS;

test(
  "Music workspace persists Chinese lyrics and measures imported WAV and MP3 in Electron",
  {
    skip: !backend || !output,
    timeout: 120_000,
  },
  async (t) => {
    mkdirSync(output, { recursive: true });
    const title = "Night Train " + randomUUID().slice(0, 8);
    const first = "[Verse 1]\n\u6708\u5149\u843d\u5728\u7a97\u8fb9";
    const second = first + "\n\n[Chorus]\n\u6211\u7b49\u706f\u5149\u56de\u5bb6";
    await withApp(t, { externalBackendPort: backend }, async (session) => {
      const openProject = async (page) => {
        await page.getByRole("link", { name: "AI Music", exact: true }).click();
        await page.getByRole("heading", { name: "AI Music", exact: true }).waitFor();
        await page.getByRole("button", { name: new RegExp(title) }).click();
      };
      const { page } = session;
      await page.getByRole("link", { name: "AI Music", exact: true }).click();
      await page.getByRole("textbox", { name: "Title", exact: true }).fill(title + " draft");
      await page.getByRole("button", { name: "Create song", exact: true }).click();
      const draftEditor = page.getByRole("region", { name: title + " draft", exact: true });
      await draftEditor.getByRole("textbox", { name: "Title", exact: true }).fill(title);
      await draftEditor
        .getByRole("textbox", { name: "Song theme", exact: true })
        .fill("Returning home");
      await draftEditor.getByRole("button", { name: "Save", exact: true }).click();
      await page.getByRole("heading", { name: title, exact: true }).waitFor();
      const editor = page.getByRole("region", { name: title, exact: true });

      const detailsTab = editor.getByRole("tab", { name: "Details", exact: true });
      await detailsTab.focus();
      await detailsTab.press("ArrowRight");
      await page.keyboard.press("Enter");
      await editor.getByRole("textbox", { name: "Lyrics editor", exact: true }).fill(first);
      await editor.getByRole("button", { name: "Save version", exact: true }).click();
      await editor.getByRole("button", { name: /^Version 1/ }).waitFor();
      await editor.getByRole("textbox", { name: "Lyrics editor", exact: true }).fill(second);
      // Leaving the route with a draft exercises renderer-local persistence.
      await page.getByRole("link", { name: "AI Music", exact: true }).evaluate(() => {
        location.hash = "#/";
      });
      await page.getByRole("heading", { name: "Home", exact: true }).waitFor();
      await openProject(page);
      await editor.getByRole("tab", { name: "AI lyrics", exact: true }).click();
      assert.equal(
        await editor.getByRole("textbox", { name: "Lyrics editor", exact: true }).inputValue(),
        second,
      );
      await editor.getByRole("button", { name: "Save version", exact: true }).click();
      await editor.getByRole("button", { name: /^Version 2/ }).waitFor();
      await editor.getByRole("button", { name: /^Version 1/ }).click();
      assert.equal(
        await editor.getByRole("textbox", { name: "Compare saved lyrics" }).inputValue(),
        first,
      );
      await page.screenshot({ path: join(output, "lyrics.png") });

      await editor.getByRole("tab", { name: "Suno prompt", exact: true }).click();
      const prompt = "Mandopop ballad, 96 BPM, close-miked vocal and acoustic piano";
      await editor.getByRole("textbox", { name: "English style prompt", exact: true }).fill(prompt);
      await editor
        .getByRole("textbox", { name: "Excluded styles", exact: true })
        .fill("festival EDM");
      await editor.getByRole("button", { name: "Save version", exact: true }).click();
      await editor.getByRole("button", { name: /^Version 1/ }).waitFor();
      await editor.getByRole("button", { name: "Copy style prompt", exact: true }).click();
      await page.getByText("Copied", { exact: true }).waitFor();
      assert.equal(await session.app.evaluate(({ clipboard }) => clipboard.readText()), prompt);
      assert.equal(
        await editor.getByRole("link", { name: "Open Suno", exact: true }).getAttribute("href"),
        "https://suno.com",
      );
      await page.screenshot({ path: join(output, "prompt.png") });

      await editor.getByRole("tab", { name: "Audio import and analysis", exact: true }).click();
      const reports = [];
      for (const name of ["tone.wav", "tone.mp3"]) {
        await editor
          .getByLabel("Choose audio file", { exact: true })
          .setInputFiles(join(output, name));
        const response = page.waitForResponse(
          (r) => r.request().method() === "POST" && r.url().includes("/audio?"),
        );
        await editor.getByRole("button", { name: "Import and analyze", exact: true }).click();
        const result = await response;
        assert.equal(result.status(), 200);
        const projectPath = new URL(result.url()).pathname
          .replace(/^\/api/, "")
          .replace(/\/audio$/, "");
        const saved = await fetch(`http://127.0.0.1:${backend}${projectPath}`);
        assert.equal(saved.status, 200);
        const asset = (await saved.json()).audioAssets.at(-1);
        assert.equal(asset.name, name);
        assert.equal(asset.analysis.status, "complete");
        assert.ok(Number.isFinite(asset.analysis.integratedLufs));
        assert.ok(Number.isFinite(asset.analysis.truePeakDbtp));
        reports.push(asset);
        await editor.getByRole("heading", { name, exact: true }).waitFor();
      }
      writeFileSync(join(output, "audio-report.json"), JSON.stringify(reports, null, 2) + "\n");
      await page.screenshot({ path: join(output, "analysis.png") });

      await session.relaunch();
      await openProject(session.page);
      const reopened = session.page.getByRole("region", { name: title, exact: true });
      await reopened.getByRole("tab", { name: "AI lyrics", exact: true }).click();
      assert.equal(
        await reopened.getByRole("textbox", { name: "Lyrics editor", exact: true }).inputValue(),
        second,
      );
      await reopened.getByRole("tab", { name: "Suno prompt", exact: true }).click();
      assert.equal(
        await reopened
          .getByRole("textbox", { name: "English style prompt", exact: true })
          .inputValue(),
        prompt,
      );
      await reopened.getByRole("tab", { name: "Audio import and analysis", exact: true }).click();
      await reopened.getByRole("heading", { name: "tone.mp3", exact: true }).waitFor();

      await session.page.evaluate(() => {
        localStorage.setItem("voicestudio.locale", "zh-CN");
        location.reload();
      });
      await session.page
        .getByRole("heading", { name: "\u0041\u0049 \u97f3\u4e50", exact: true })
        .waitFor();
      await session.page.getByRole("button", { name: new RegExp(title) }).click();
      await reopened
        .getByRole("tab", { name: "\u97f3\u9891\u5bfc\u5165\u4e0e\u5206\u6790", exact: true })
        .click();
      await reopened.getByRole("heading", { name: "tone.mp3", exact: true }).waitFor();
      await session.page.screenshot({ path: join(output, "analysis-zh-CN.png") });
      await session.page.setViewportSize({ width: 880, height: 720 });
      const main = session.page.getByRole("main", { name: "\u0041\u0049 \u97f3\u4e50" });
      assert.ok(await main.evaluate((element) => element.scrollWidth <= element.clientWidth + 1));
    });
  },
);
