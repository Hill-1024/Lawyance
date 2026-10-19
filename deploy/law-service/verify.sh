#!/usr/bin/env bash
# Run locally first, then from a customer host using the HTTPS tunnel hostname.
# Uses a separate rpm=1 key for the 429 assertion; never flood a customer key.
set -euo pipefail
umask 077

URL="${LAW_VERIFY_URL:-http://127.0.0.1:8084}"
URL="${URL%/}"
: "${LAW_VERIFY_KEY:?Set LAW_VERIFY_KEY to a dedicated acceptance key (rpm >= 10)}"
: "${LAW_ACCEPTANCE_RATE_KEY:?Set LAW_ACCEPTANCE_RATE_KEY to a NEW dedicated rpm=1 key}"
[[ "$LAW_VERIFY_KEY" != "$LAW_ACCEPTANCE_RATE_KEY" ]] || { echo 'Use a separate rate-test key.' >&2; exit 2; }
for credential in "$LAW_VERIFY_KEY" "$LAW_ACCEPTANCE_RATE_KEY" "${LAW_CANARY_KEY:-}"; do
  [[ -z "$credential" || "$credential" =~ ^[A-Za-z0-9_-]+$ ]] || { echo 'Unexpected key characters.' >&2; exit 2; }
done
python3 - "$URL" <<'PY'
import sys
from urllib.parse import urlsplit
url = urlsplit(sys.argv[1])
if url.username or url.password or url.query or url.fragment or url.path not in ('', '/'):
    raise SystemExit('Use a service origin URL without credentials, query, fragment or path.')
if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in {'127.0.0.1', 'localhost', '::1'}):
    raise SystemExit('Use HTTPS outside the loopback interface.')
PY

WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT

request() {
  local expected="$1" method="$2" path="$3" key="$4" body="${5:-}" status
  local -a options=(--silent --show-error --connect-timeout 3 --max-time 20 --request "$method"
    --dump-header "$WORK/headers" --output "$WORK/body" --write-out '%{http_code}')
  [[ -z "$body" ]] || options+=(--header 'Content-Type: application/json' --data-raw "$body")
  # Config via stdin keeps the key out of curl's process arguments and output.
  if [[ -n "$key" ]]; then
    status="$(printf 'header = "Authorization: Bearer %s"\n' "$key" | curl --config - "${options[@]}" "$URL$path")"
  else
    status="$(curl "${options[@]}" "$URL$path")"
  fi
  [[ "$status" == "$expected" ]] || { printf 'FAIL %s %s: expected %s, got %s\n' "$method" "$path" "$expected" "$status" >&2; exit 1; }
  printf 'PASS %s %s -> %s\n' "$method" "$path" "$status"
}

request 200 GET /healthz ''
python3 - "$WORK/body" <<'PY'
import json, sys
if json.load(open(sys.argv[1], encoding='utf-8')).get('ready') is not True:
    raise SystemExit('Health response is not ready')
PY
request 401 GET /v1/meta ''
request 200 GET /v1/meta "$LAW_VERIFY_KEY"
python3 - "$WORK/body" <<'PY'
import json, os, re, sys
body = json.load(open(sys.argv[1], encoding='utf-8'))
if (not isinstance(body, dict)
    or type(body.get('schema_version')) is not int or body['schema_version'] <= 0
    or type(body.get('file_count')) is not int or body['file_count'] <= 0
    or not isinstance(body.get('content_sha256'), str)
    or not re.fullmatch('[0-9a-f]{64}', body['content_sha256'])):
    raise SystemExit('Invalid or empty law-service meta')
if os.environ.get('LAW_VERIFY_SHA256') and body['content_sha256'] != os.environ['LAW_VERIFY_SHA256']:
    raise SystemExit('Manifest SHA-256 differs from the approved data release')
print('PASS meta schema/version and nonempty corpus (compare with approved release)')
PY

make_body() {
  python3 - "$1" <<'PY'
import json, os, sys
title = os.environ.get('LAW_VERIFY_TITLE', '中华人民共和国民法典')
number = os.environ.get('LAW_VERIFY_NUMBER', '第一条')
payload = {
    'exact': {'title': title, 'number': number},
    'search': {'query': os.environ.get('LAW_VERIFY_QUERY', '违约责任'), 'limit': 2},
    'links': {'text': os.environ.get('LAW_VERIFY_TEXT', f'《{title}》{number}'), 'limit': 2},
}[sys.argv[1]]
print(json.dumps(payload))
PY
}
check_body() {
  python3 - "$WORK/body" "$1" <<'PY'
import json, sys
body = json.load(open(sys.argv[1], encoding='utf-8'))
kind = sys.argv[2]
if not isinstance(body, dict) or body.get('success') is not True:
    raise SystemExit(f'{kind}: service returned no successful match; choose a known fixture with LAW_VERIFY_*')
if kind == 'exact':
    data = body.get('data')
    valid = isinstance(data, dict) and all(isinstance(data.get(k), str) and data[k].strip() for k in ('law_name', 'article_number', 'content'))
elif kind == 'search':
    data = body.get('data')
    valid = isinstance(data, list) and 1 <= len(data) <= 2 and all(isinstance(row, dict) and isinstance(row.get('content'), str) and row['content'].strip() for row in data)
else:
    references = body.get('references')
    valid = isinstance(body.get('text'), str) and bool(body['text'].strip()) and isinstance(references, list) and 1 <= len(references) <= 2 and any(isinstance(row, dict) and isinstance(row.get('url'), str) and row['url'].startswith(('http://', 'https://')) for row in references)
if not valid:
    raise SystemExit(f'{kind}: missing or malformed nonempty result')
print(f'PASS {kind} successful nonempty result')
PY
}
request 200 POST /v1/laws/exact "$LAW_VERIFY_KEY" "$(make_body exact)"
check_body exact
request 200 POST /v1/laws/search "$LAW_VERIFY_KEY" "$(make_body search)"
check_body search
request 200 POST /v1/laws/links "$LAW_VERIFY_KEY" "$(make_body links)"
check_body links
# Rate-test key must be freshly issued or idle for at least one full rate window.
request 200 GET /v1/meta "$LAW_ACCEPTANCE_RATE_KEY"
request 429 GET /v1/meta "$LAW_ACCEPTANCE_RATE_KEY"
python3 - "$WORK/headers" <<'PY'
import sys
if not any(line.lower().startswith('retry-after:') for line in open(sys.argv[1], encoding='utf-8')):
    raise SystemExit('429 is missing Retry-After')
print('PASS 429 Retry-After')
PY

if [[ -n "${LAW_CANARY_KEY:-}" ]]; then
  request 200 POST /v1/laws/search "$LAW_CANARY_KEY" '{"query":"__lawver_canary__","limit":1}'
  python3 - "$WORK/body" <<'PY'
import json, sys
body = json.load(open(sys.argv[1], encoding='utf-8'))
if body.get('canary') is not True or not body.get('data') or not body['data'][0].get('content', '').startswith('CANARY:'):
    raise SystemExit('Canary diagnostic response failed')
print('PASS dedicated canary diagnostic')
PY
fi
echo 'Acceptance checks passed. Disable acceptance keys after recording the server-side audit results.'
