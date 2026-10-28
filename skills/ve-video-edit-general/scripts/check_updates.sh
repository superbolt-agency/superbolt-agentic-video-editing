#!/bin/bash
# Usage: check_updates.sh [--now]
# Is there a newer version of the video-editing skills on GitHub? Checks at most once a day unless --now.
# The local clone's path is recorded in ~/.claude/skills/.video-editing-source by SETUP.md step 8.
# Prints one status line: UP TO DATE / UPDATE AVAILABLE (+ what changed) / SKIPPED / CAN'T CHECK. Never changes anything.
S="$HOME/.claude/skills/.video-editing-source"; STAMP="$HOME/.claude/skills/.video-editing-last-check"
[ -f "$S" ] || { echo "CAN'T CHECK: no source folder recorded (re-run SETUP.md step 8 from the cloned folder)"; exit 0; }
R=$(head -1 "$S")
git -C "$R" rev-parse --git-dir >/dev/null 2>&1 || { echo "CAN'T CHECK: $R is no longer a git clone (moved or deleted?)"; exit 0; }
if [ "$1" != "--now" ] && [ -f "$STAMP" ] && [ $(( $(date +%s) - $(stat -f %m "$STAMP") )) -lt 72000 ]; then
  echo "SKIPPED: checked within the last day"; exit 0
fi
# fetch with a 20s cap so a slow or missing network never holds up an edit
GIT_TERMINAL_PROMPT=0 perl -e 'alarm 20; exec @ARGV' git -C "$R" fetch -q 2>/dev/null || { echo "CAN'T CHECK: couldn't reach GitHub (offline?)"; exit 0; }
touch "$STAMP"
N=$(git -C "$R" rev-list --count HEAD..@{u} 2>/dev/null) || { echo "CAN'T CHECK: the clone has no upstream branch"; exit 0; }
if [ "$N" -gt 0 ]; then
  echo "UPDATE AVAILABLE: $N new change(s) in $R"
  git -C "$R" log --format='  - %s (%ad)' --date=short HEAD..@{u} | head -10
  [ -n "$(git -C "$R" status --porcelain)" ] && echo "  note: the clone has local edits; updating needs care (git pull --ff-only will refuse if they conflict)"
else
  # the clone may be current while the installed copy is stale (e.g. someone ran git pull but didn't reinstall)
  for s in ve-video-edit-general apply-notes video-qa; do
    if [ -n "$(diff -rq "$R/skills/$s" "$HOME/.claude/skills/$s" -x __pycache__ -x .DS_Store -x textscan -x video-editing-standards.md -x brand-house-style.md 2>&1)" ]; then
      echo "INSTALLED COPY OUT OF DATE: $s differs from $R (re-run SETUP.md step 8)"; exit 0
    fi
  done
  echo "UP TO DATE"
fi
