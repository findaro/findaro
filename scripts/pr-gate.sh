#!/usr/bin/env bash
# Turn the "required checks before merging" gate on main on or off (GitHub ruleset "protect main").
#
#   scripts/pr-gate.sh status    # show whether merges wait for CI
#   scripts/pr-gate.sh off       # merges no longer wait for CI (checks still run and report on every PR)
#   scripts/pr-gate.sh on        # merges wait for python, js and e2e again
#
# Only the required-checks rule changes. No force pushes, no deleting main and PR-only changes stay in force.
# Needs `gh` logged in as an admin of the repository.
set -euo pipefail
REPO="${FINDARO_REPO:-findaro/findaro}"
CHECKS='[{"context":"python (ruff, pytest)"},{"context":"js (types, build, size budgets)"},{"context":"e2e (Playwright, full stack)"}]'

id=$(gh api "repos/$REPO/rulesets" --jq '.[] | select(.name == "protect main") | .id')
[ -n "$id" ] || { echo "ruleset 'protect main' not found in $REPO" >&2; exit 1; }
current=$(gh api "repos/$REPO/rulesets/$id")
gated=$(echo "$current" | jq '[.rules[] | select(.type == "required_status_checks")] | length')

case "${1:-status}" in
  status)
    if [ "$gated" -gt 0 ]; then echo "on: merges to main wait for CI"; else echo "off: merges to main don't wait for CI"; fi ;;
  off|on)
    rules=$(echo "$current" | jq '[.rules[] | select(.type != "required_status_checks")]')
    if [ "$1" = on ]; then
      rules=$(echo "$rules" | jq --argjson c "$CHECKS" '. + [{"type": "required_status_checks", "parameters":
        {"strict_required_status_checks_policy": false, "required_status_checks": $c}}]')
    fi
    echo "$current" | jq --argjson r "$rules" '{name, target, enforcement, conditions, rules: $r}' |
      gh api -X PUT "repos/$REPO/rulesets/$id" --input - >/dev/null
    "$0" status ;;
  *) echo "usage: $0 status|on|off" >&2; exit 2 ;;
esac
