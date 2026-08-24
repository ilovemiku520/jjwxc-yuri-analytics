#!/bin/sh
set -eu

if [ -z "${DATABASE_URL:-}" ]; then
  echo '{"status":"failed","error":"database_url_missing"}'
  exit 2
fi

backup_dir="${BACKUP_DIR:-/backups}"
keep_count="${BACKUP_KEEP:-7}"
case "$keep_count" in
  ''|*[!0-9]*)
    echo '{"status":"failed","error":"invalid_backup_keep"}'
    exit 2
    ;;
esac
if [ "$keep_count" -lt 1 ] || [ "$keep_count" -gt 31 ]; then
  echo '{"status":"failed","error":"invalid_backup_keep"}'
  exit 2
fi

mkdir -p "$backup_dir"
umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_path="$backup_dir/jjwxc-$stamp.dump"
temporary_path="$backup_dir/.jjwxc-$stamp.dump.tmp"
trap 'rm -f "$temporary_path"' EXIT HUP INT TERM

pg_dump "$DATABASE_URL" --format=custom --compress=9 --file="$temporary_path"
pg_restore --list "$temporary_path" >/dev/null
mv "$temporary_path" "$final_path"
sha256sum "$final_path" >"$final_path.sha256"

ls -1t "$backup_dir"/jjwxc-*.dump 2>/dev/null | awk -v keep="$keep_count" 'NR > keep' |
while IFS= read -r stale_path; do
  rm -f -- "$stale_path" "$stale_path.sha256"
done

size_bytes="$(wc -c <"$final_path" | tr -d ' ')"
printf '{"status":"completed","backup":"%s","size_bytes":%s,"retained":%s}\n' \
  "$(basename "$final_path")" "$size_bytes" "$keep_count"
