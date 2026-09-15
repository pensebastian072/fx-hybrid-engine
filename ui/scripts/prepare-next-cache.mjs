import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

function isOneDrivePath(value) {
  return value.toLowerCase().includes(`${path.sep}onedrive${path.sep}`);
}

function ensureDirectory(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function ensureJunction(linkPath, targetPath) {
  if (fs.existsSync(linkPath)) {
    const stats = fs.lstatSync(linkPath);
    if (stats.isSymbolicLink()) {
      const realTarget = fs.realpathSync.native(linkPath);
      if (path.resolve(realTarget) === path.resolve(targetPath)) {
        return;
      }
    }

    removeIfPresent(linkPath);
  }

  fs.symlinkSync(targetPath, linkPath, 'junction');
}

function removeIfPresent(targetPath) {
  if (!fs.existsSync(targetPath)) {
    return;
  }

  fs.rmSync(targetPath, { recursive: true, force: true });
}

function main() {
  const projectRoot = process.cwd();
  const nextPath = path.join(projectRoot, '.next');

  if (process.platform !== 'win32' || !isOneDrivePath(projectRoot)) {
    return;
  }

  const cacheRoot = path.join(os.homedir(), 'AppData', 'Local', 'fx-hybrid-engine', 'next-cache');
  const cacheTarget = path.join(cacheRoot, 'ui');
  const projectNodeModules = path.join(projectRoot, 'node_modules');
  const cacheNodeModules = path.join(cacheTarget, 'node_modules');

  ensureDirectory(cacheTarget);
  ensureJunction(cacheNodeModules, projectNodeModules);

  if (fs.existsSync(nextPath)) {
    const stats = fs.lstatSync(nextPath);
    if (stats.isSymbolicLink()) {
      const realTarget = fs.realpathSync.native(nextPath);
      if (path.resolve(realTarget) === path.resolve(cacheTarget)) {
        return;
      }
    }

    removeIfPresent(nextPath);
  }

  fs.symlinkSync(cacheTarget, nextPath, 'junction');
  process.stdout.write(`Linked .next to ${cacheTarget}\n`);
}

main();