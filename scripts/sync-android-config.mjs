/*
 * 模块描述：从 package.json 同步 Android versionName、versionCode 与原生直连域名。
 */

import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, '..');
const packagePath = join(rootDir, 'package.json');
const gradlePath = join(rootDir, 'android', 'app', 'build.gradle');
const networkSecurityPath = join(rootDir, 'android', 'app', 'src', 'main', 'res', 'xml', 'network_security_config.xml');

const packageJson = JSON.parse(readFileSync(packagePath, 'utf8'));
const version = packageJson.version;
const semverMatch = typeof version === 'string'
  ? version.match(/^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/)
  : null;

if (!semverMatch) {
  console.error(`Invalid package.json version "${version}". Expected SemVer like x.y.z or x.y.z-prerelease.`);
  process.exit(1);
}

const nativeApiBase = packageJson.appConfig?.nativeApiBase;
let nativeHostname = '';
try {
  nativeHostname = nativeApiBase ? new URL(nativeApiBase).hostname : '';
} catch {
  nativeHostname = '';
}
if (!nativeHostname) {
  console.error('Missing or invalid package.json appConfig.nativeApiBase. Expected an absolute origin, e.g. "https://cn-origin.lawver.dev".');
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

const domainEntry = /<domain includeSubdomains="false">([^<]*)<\/domain>/.exec(readFileSync(networkSecurityPath, 'utf8'));
if (!domainEntry) {
  console.error(`Failed to sync domain into network_security_config.xml: no <domain> entry matched in ${networkSecurityPath}.`);
  process.exit(1);
}

if (domainEntry[1] !== nativeHostname) {
  const nextNetworkSecurity = readFileSync(networkSecurityPath, 'utf8')
    .replace(/<domain includeSubdomains="false">[^<]*<\/domain>/, `<domain includeSubdomains="false">${nativeHostname}</domain>`);
  writeFileSync(networkSecurityPath, nextNetworkSecurity, 'utf8');
  console.log(`Synced Android network security domain to ${nativeHostname}.`);
} else {
  console.log(`Android network security domain already matches package.json (${nativeHostname}).`);
}
