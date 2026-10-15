#!/bin/bash
# Cron entry point for sync_snapshots.py. Cron starts with an empty environment,
# and the venv's python needs the Python module's libpython (see _slurm_job.sbatch).
#   crontab: 30 9 * * * /mnt/personal/ullriher/community-notes/script/cron_sync.sh
source /etc/profile.d/lmod.sh 2>/dev/null || source /opt/ohpc/admin/lmod/lmod/init/bash
ml Python/3.12.3-GCCcore-13.3.0
ml OpenSSL/3
source /mnt/personal/ullriher/venvs/aug25/bin/activate

cd /mnt/personal/ullriher/community-notes
python sync_snapshots.py "$@" >> /mnt/personal/ullriher/community-notes/logs/cron/sync_$(date +%Y-%m).log 2>&1
