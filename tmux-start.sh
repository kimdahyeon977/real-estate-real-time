#!/usr/bin/env bash
# tmux 세션 'realty' 안에서 봇을 띄운다. 이미 떠 있으면 아무것도 하지 않는다.
set -euo pipefail
DIR="$(dirname "$(readlink -f "$0")")"
tmux has-session -t realty 2>/dev/null && { echo "이미 실행 중 (tmux attach -t realty)"; exit 0; }
tmux new-session -d -s realty -c "$DIR" "$DIR/run.sh 2>&1 | tee -a $DIR/watcher.log"
echo "시작됨. 보려면: tmux attach -t realty"
