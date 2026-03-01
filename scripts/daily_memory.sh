#!/usr/bin/env bash

WS="$HOME/AI/openclaw-workspace"
DATE=$(date +%Y-%m-%d)
FILE="$WS/memory/daily/$DATE.md"

mkdir -p "$WS/memory/daily"

echo "# $DATE" > "$FILE"
echo "" >> "$FILE"
echo "## 今日主要工作" >> "$FILE"
echo "- 自动生成摘要" >> "$FILE"
echo "" >> "$FILE"
echo "## 技术调整" >> "$FILE"
echo "- " >> "$FILE"
echo "" >> "$FILE"
echo "## 关键决策" >> "$FILE"
echo "- " >> "$FILE"
echo "" >> "$FILE"
echo "## 待办" >> "$FILE"
echo "- " >> "$FILE"

cd "$WS"
git add .
git commit -m "daily memory $DATE" >/dev/null 2>&1 || true
git push >/dev/null 2>&1 || true
