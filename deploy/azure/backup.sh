#!/bin/sh
# Backs up the incident database (SQLite, the `nexus_nexus-data` volume) on the VM and keeps the 7 newest copies.
#   sh deploy/azure/backup.sh            # run on the VM
# Install a daily run:  (crontab -l 2>/dev/null; echo "15 3 * * * sh $HOME/nexus/deploy/azure/backup.sh >> $HOME/backups/backup.log 2>&1") | crontab -
# Restore:  docker run --rm -v nexus_nexus-data:/d -v $HOME/backups:/b alpine sh -c "cd /d && tar xzf /b/<file>.tgz --strip-components=1"
set -eu
DEST="${NEXUS_BACKUP_DIR:-$HOME/backups}"
VOLUME="${NEXUS_DATA_VOLUME:-nexus_nexus-data}"
mkdir -p "$DEST"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="$DEST/nexus-data-$STAMP.tgz"
docker run --rm -v "$VOLUME":/d:ro -v "$DEST":/b alpine tar czf "/b/nexus-data-$STAMP.tgz" -C / d
# keep the newest 7
ls -1t "$DEST"/nexus-data-*.tgz | tail -n +8 | xargs -r rm -f
echo "backup written: $FILE ($(du -h "$FILE" | cut -f1))"
