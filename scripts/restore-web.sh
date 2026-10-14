#!/usr/bin/env bash
# Linux server only. Defaults to validation; --apply explicitly performs restore.
set -euo pipefail

snapshot="${1:?Usage: restore-web.sh SNAPSHOT.tar.gz [--apply]}"
mode="${2:---check}"
expected="85bc338f9a93ff7712852ff91fd379b07929e5d55d35ead34f7df74eb3213768"
actual="$(sha256sum -- "$snapshot" | cut -d ' ' -f 1)"
[[ "$actual" == "$expected" ]] || { echo 'Snapshot checksum mismatch.' >&2; exit 1; }
gzip -t -- "$snapshot"
if [[ "$mode" == '--check' ]]; then
    echo 'Snapshot verified. Use --apply on 8.130.160.137 to restore the webpage.'
    exit 0
fi
[[ "$mode" == '--apply' ]] || { echo 'Unknown mode.' >&2; exit 1; }
[[ "$EUID" -eq 0 ]] || { echo 'Run as root on the target Linux server.' >&2; exit 1; }

live='/data/web/dist'
route='/etc/nginx/conf.d/web.conf'
[[ -d "$live" && ! -L "$live" && -f "$route" && ! -L "$route" ]] || {
    echo 'Expected deployment paths are absent or symlinks; no changes made.' >&2
    exit 1
}
backup="/var/backups/rainstorm/web-before-restore-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p -m 700 -- "$backup"
tar -xzf "$snapshot" -C "$backup"
[[ -f "$backup/data/web/dist/index.html" && -f "$backup/etc/nginx/conf.d/web.conf" ]]
cp -p -- "$route" "$backup/previous-web.conf"
mv -- "$live" "$backup/previous-dist"

restore_previous() {
    local status="$?"
    trap - ERR
    if [[ -d "$live" ]]; then mv -- "$live" "$backup/failed-dist"; fi
    mv -- "$backup/previous-dist" "$live"
    cp -p -- "$backup/previous-web.conf" "$route"
    if nginx -t; then
        if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl start nginx; fi
    fi
    echo "Restore failed; previous webpage restored. Recovery files: $backup" >&2
    exit "$status"
}
trap restore_previous ERR
cp -a -- "$backup/data/web/dist" "$live"
cp -p -- "$backup/etc/nginx/conf.d/web.conf" "$route"
nginx -t
if systemctl is-active --quiet nginx; then systemctl reload nginx; else systemctl start nginx; fi
trap - ERR
echo "Web baseline restored. Previous deployment retained at: $backup"
echo 'Check http://8.130.160.137/home/analyse in a browser.'
