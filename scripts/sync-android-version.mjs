/*
 * 模块描述：从 package.json 同步 Android versionName 与 versionCode。
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, '..');
const packagePath = join(rootDir, 'package.json');
const gradlePath = join(rootDir, 'android', 'app', 'build.gradle');

const packageJson = JSON.parse(readFileSync(packagePath, 'utf8'));
const version = packageJson.version;
const semverMatch = typeof version === 'string'
  ? version.match(/^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/)
  : null;

if (!semverMatch) {
  console.error(`Invalid package.json version "${version}". Expected SemVer like x.y.z or x.y.z-prerelease.`);
  process.exit(1);
}

const [, majorRaw, minorRaw, patchRaw] = semverMatch;
const major = Number(majorRaw);
const minor = Number(minorRaw);
const patch = Number(patchRaw);
const versionCode = major * 1_000_000 + minor * 1_000 + patch;

let gradle = readFileSync(gradlePath, 'utf8');
const nextGradle = gradle
  .replace(/versionCode\s+\d+/, `versionCode ${versionCode}`)
  .replace(/versionName\s+"[^"]*"/, `versionName "${version}"`);

if (nextGradle !== gradle) {
  writeFileSync(gradlePath, nextGradle, 'utf8');
  console.log(`Synced Android versionName ${version} and versionCode ${versionCode}.`);
} else {
  console.log(`Android version already matches package.json (${version}, code ${versionCode}).`);
}
