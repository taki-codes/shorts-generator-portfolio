import fs from 'node:fs';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {selectComposition, renderMedia} from '@remotion/renderer';

// Only local files, no shell interpolation, API key, or cloud rendering.
async function main() {
const request = JSON.parse(fs.readFileSync(process.argv[2], 'utf8').replace(/^\uFEFF/, ''));
const serveUrl = await bundle({
  entryPoint: request.entryPoint,
  outDir: request.bundleDir,
  webpackOverride: (config) => ({...config, resolve: {
    ...config.resolve,
    modules: [path.resolve('node_modules'), ...(config.resolve?.modules ?? ['node_modules'])],
  }}),
});
const browserExecutable = request.browserExecutable ?? null;
const inputProps = request.inputProps;
const selected = await selectComposition({serveUrl, id: request.compositionId, inputProps, browserExecutable});
const composition = {...selected, width: inputProps.width, height: inputProps.height,
  fps: inputProps.fps, durationInFrames: inputProps.durationInFrames};
await renderMedia({serveUrl, composition, inputProps, browserExecutable,
  outputLocation: request.output, codec: 'prores', proResProfile: '4444',
  imageFormat: 'png', pixelFormat: 'yuva444p10le', muted: true,
  concurrency: 2, logLevel: 'warn'});
}
main().catch((error) => {console.error(error.message ?? error, error.stack?.slice(0, 2000) ?? ''); process.exitCode = 1;});
