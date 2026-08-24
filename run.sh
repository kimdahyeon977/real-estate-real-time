#!/usr/bin/env bash
# 매물 감시 봇 실행기. vendor/ 에 curl_cffi 를 넣어두었으므로 pip 없이도 동작한다.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
export PYTHONPATH="$PWD/vendor${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
exec python3 -m watcher.main "$@"
