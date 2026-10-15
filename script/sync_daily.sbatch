#!/bin/bash
#SBATCH --partition cpu
#SBATCH --time 12:00:00
#SBATCH --cpus-per-task 1
#SBATCH --mem 4G
#SBATCH --job-name cn-sync
#SBATCH --output /mnt/personal/ullriher/community-notes/logs/cron/slurm-%j.out

# Daily Community Notes snapshot sync. scrontab is disabled on this cluster, so the
# job books its own next run first; even if this run fails, the chain continues.
#   start: sbatch script/sync_daily.sbatch
#   stop:  scancel --name cn-sync
SELF=/mnt/personal/ullriher/community-notes/script/sync_daily.sbatch
RUN_AT=14:00

# Only queue tomorrow's run if one isn't pending already (guards against double chains).
if [ -z "$(squeue -u "$USER" -h -n cn-sync -t PENDING -o %i)" ]; then
    sbatch --begin="$(date -d tomorrow +%Y-%m-%d)T$RUN_AT" "$SELF"
fi

/mnt/personal/ullriher/community-notes/script/cron_sync.sh
