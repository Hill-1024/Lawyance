/*
 * 模块描述：以项目可用的 JDK 21 运行 Android Gradle 任务，优先复用 Android Studio 自带 JBR。
 */

import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, '..');
const androidDir = join(rootDir, 'android');

const gradleArgs = process.argv.slice(2);
if (gradleArgs.length === 0) {
  console.error('Usage: node scripts/run-android-gradle.mjs <gradle-task> [...args]');
  process.exit(1);
}

const javaMajorVersion = (javaHome) => {
  if (!javaHome) return null;
  const javaBin = join(javaHome, 'bin', 'java');
  if (!existsSync(javaBin)) return null;
  const result = spawnSync(javaBin, ['-version'], { encoding: 'utf8' });
  const output = `${result.stdout || ''}\n${result.stderr || ''}`;
  const match = output.match(/version "(\d+)(?:\.|\+|")/);
  return match ? Number(match[1]) : null;
};

const androidStudioJbrCandidates = [
  '/Applications/Android Studio.app/Contents/jbr/Contents/Home',
  '/Applications/Android Studio Preview.app/Contents/jbr/Contents/Home',
];

const resolveJavaHome = () => {
  if (javaMajorVersion(process.env.JAVA_HOME) === 21) return process.env.JAVA_HOME;
  return androidStudioJbrCandidates.find(candidate => javaMajorVersion(candidate) === 21) || process.env.JAVA_HOME;
};

const javaHome = resolveJavaHome();
const env = { ...process.env };
if (javaHome) env.JAVA_HOME = javaHome;

const result = spawnSync('./gradlew', gradleArgs, {
  cwd: androidDir,
  env,
  stdio: 'inherit',
});

process.exit(result.status ?? 1);
