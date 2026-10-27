#!/usr/bin/env bash
# GitHub 예약 실행은 몇 시간씩 밀리므로, 한 번 시작된 실행 안에서 5분 간격으로 감시를 반복한다.
# 약 5시간 40분 뒤 끝내고 GITHUB_TOKEN으로 다음 실행을 직접 예약한다(workflow_dispatch). 외부 토큰·유료 서비스 없음.
set -u
LOOP_MINUTES="${LOOP_MINUTES:-340}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-300}"
end=$(( $(date +%s) + LOOP_MINUTES * 60 ))
ws="$RUNNER_TEMP/watch-state-worktree"

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'

save_state() {
  test -f state.json && test -f report.json || return 0
  rm -rf "$ws"; git worktree prune
  if git fetch -q --depth=1 origin watch-state 2>/dev/null; then
    git worktree add -q --detach "$ws" FETCH_HEAD
  else
    git worktree add -q --detach "$ws" HEAD
    (cd "$ws" && git checkout -q --orphan tmp-state && git rm -rqf . >/dev/null)
  fi
  cp state.json report.json "$ws/"
  (cd "$ws" && git add state.json report.json \
    && { git diff --cached --quiet || { git commit -qm 'Update public price observations and delivery checkpoint' && git push -q origin HEAD:watch-state; }; })
}

runs=0; fails=0
while :; do
  start=$(date +%s)
  runs=$((runs+1))
  if python3 watch.py; then :; else fails=$((fails+1)); echo "collect failed (run $runs)"; fi
  save_state || echo "state save failed (run $runs)"
  next=$(( start + INTERVAL_SECONDS ))
  [ "$next" -ge "$end" ] && break
  now=$(date +%s); [ "$next" -gt "$now" ] && sleep $(( next - now ))
done
echo "loop finished: $runs runs, $fails failed"

# 다음 반복 실행을 바로 예약 (GITHUB_TOKEN의 workflow_dispatch는 새 실행을 만든다)
if [ "${SELF_REDISPATCH:-1}" = 1 ]; then
  curl -fsS -X POST -H "Authorization: Bearer $GITHUB_TOKEN" -H 'Accept: application/vnd.github+json' \
    "https://api.github.com/repos/$GITHUB_REPOSITORY/actions/workflows/watch.yml/dispatches" \
    -d '{"ref":"main"}' && echo 'next loop dispatched' || echo 'redispatch failed; cron schedule remains as backup'
fi
[ "$fails" -lt "$runs" ]
