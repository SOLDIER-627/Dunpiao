#!/bin/bash
# 工作区 → Dunpiao 归档仓库单向同步（Dunpiao 有独立 git，单向：本脚本 → git push）
# 规矩：README/TASKS 一律改工作区源文件（rsync 会覆盖 Dunpiao 侧同名文件）。
set -euo pipefail
cd "$(dirname "$0")/.."

rsync -a --delete \
  --exclude '.git' \
  --exclude 'Dunpiao' \
  --exclude 'TASKS.md' \
  --exclude 'archive' \
  --exclude '.venv' \
  --exclude '.android-sdk' \
  --exclude '.android-avd' \
  --exclude '.pi-sessions' \
  --exclude 'reference' \
  --exclude 'pagesamples' \
  --exclude 'logs' \
  --exclude 'screenshots' \
  --exclude 'artifacts' \
  --exclude '__pycache__' \
  --exclude '.DS_Store' \
  --exclude 'config.local.*' \
  --exclude 'config.jsonc' \
  --exclude 'archive/snapshots' \
  --exclude '分工计划.md' \
  --exclude '整体计划.md' \
  --exclude '调研_*.md' \
  --exclude 'docs/research' \
  --exclude 'docs/architecture' \
  --exclude 'docs/setup' \
  --exclude 'docs/archive' \
  --exclude 'docs/抢票*' \
  ./ Dunpiao/

echo "同步完成。记得在 Dunpiao/ 内 git add -A && git commit && git push"
