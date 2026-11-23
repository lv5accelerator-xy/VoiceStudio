import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { bundle } from '@remotion/bundler';
import { renderMedia, selectComposition } from '@remotion/renderer';

const [browserExecutable, outputLocation, w, h, seconds, beats] = process.argv.slice(2);
const [width, height, duration, bpm] = [w, h, seconds, beats].map(Number);
if (
  !browserExecutable || !isAbsolute(browserExecutable) || !outputLocation || !isAbsolute(outputLocation)
  || !['1080x1920', '1920x1080'].includes(`${width}x${height}`)
  || !(duration > 0 && duration <= 1200) || !(bpm >= 20 && bpm <= 300)
) throw new Error('Expected absolute browser and output paths, a 1080p canvas, duration and BPM');

const directory = await mkdtemp(join(tmpdir(), 'voicestudio-mv-'));
const inputProps = { width, height, duration, bpm };
try {
  const serveUrl = await bundle({
    entryPoint: fileURLToPath(new URL('./scene.jsx', import.meta.url)),
    outDir: directory,
    enableCaching: false,
  });
  const composition = await selectComposition({ serveUrl, id: 'MusicBackdrop', inputProps, browserExecutable });
  await renderMedia({
    serveUrl, composition, inputProps, browserExecutable, outputLocation,
    codec: 'h264', concurrency: 1, muted: true,
  });
} finally {
  await rm(directory, { recursive: true, force: true });
}
