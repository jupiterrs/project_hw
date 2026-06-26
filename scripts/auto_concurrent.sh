#!/bin/bash
# Auto-concurrency runner for AweAgent with GLM-5.2-fp8
# - 9 AM to 6 PM: 4 concurrent, 16 tasks per batch (~15-20 min cycles)
# - 6 PM to 9 AM: 8 concurrent, 32 tasks per batch (~15-20 min cycles)
# - Resumes from completed instances safely
# - Protected against OverlayFS and disk capacity crashes via /tmp-tini

set -e

# === Timezone (HK) ===
export TZ=Asia/Hong_Kong

# === Docker Safety Workspace Setup ===
export TMPDIR=/tmp-tini/nurdaulet_docker_workspace
export XDG_CACHE_HOME=/tmp-tini/nurdaulet_docker_workspace
mkdir -p $TMPDIR

# === Config ===
export BASE_DIR=/public/lianghong/nurdaulet_absattarov
export DATA_FILE=$BASE_DIR/data/task_instances/available_images.jsonl
export OUTPUT_DIR=$BASE_DIR/results/scale_swe_glm52
export LLM_CONFIG=$BASE_DIR/configs/llm/glm52_api.yaml
export TASK_CONFIG=$BASE_DIR/configs/tasks/scale_swe_openai_fn.yaml
export REMAINING_FILE=$BASE_DIR/data/task_instances/remaining_glm52.jsonl
export CHUNK_FILE=$BASE_DIR/data/task_instances/chunk_glm52.jsonl
export COMPLETED_IDS=$TMPDIR/completed_ids_glm52.txt

cd $BASE_DIR/AweAgent
source .venv/bin/activate
source ../.env

mkdir -p $OUTPUT_DIR

while true; do
    # Decide concurrency AND batch chunk size based on time of day
    HOUR=$(date +%H)
    if [ $HOUR -ge 9 ] && [ $HOUR -lt 18 ]; then
        CONCURRENT=4
        CHUNK_SIZE=16 # 4 containers doing 4 tasks each
        PERIOD="daytime"
    else
        CONCURRENT=8
        CHUNK_SIZE=32 # 8 containers doing 4 tasks each
        PERIOD="nighttime"
    fi

    echo ""
    echo "===================================================="
    echo "[$(date)] Starting New Cycle — $PERIOD mode"
    echo "  Concurrency Target: $CONCURRENT | Chunk Size: $CHUNK_SIZE"
    echo "===================================================="

    # 1. Build completed IDs safely from ALL existing trajectories
    python3 -c "
import json, glob, os
ids = set()
output_dir = os.environ['OUTPUT_DIR']
completed_ids_path = os.environ['COMPLETED_IDS']

for f in glob.glob(f'{output_dir}/*/trajectories.jsonl'):
    with open(f, 'r') as open_file:
        for line_num, line in enumerate(open_file, 1):
            line = line.strip()
            if not line: continue
            try:
                r = json.loads(line)
                if 'instance_id' in r:
                    ids.add(r['instance_id'])
            except Exception as e:
                print(f'  Warning: failed to parse line {line_num} in {f}: {e}')

print(f'  Completed so far: {len(ids)} instances')
with open(completed_ids_path, 'w') as out:
    for i in ids:
        out.write(i + '\n')
"

    # 2. Create remaining.jsonl master list
    python3 -c "
import json, os
completed_ids_path = os.environ['COMPLETED_IDS']
data_file = os.environ['DATA_FILE']
remaining_file = os.environ['REMAINING_FILE']

if os.path.exists(completed_ids_path) and os.path.getsize(completed_ids_path) > 0:
    with open(completed_ids_path) as f:
        completed = set(line.strip() for line in f if line.strip())
else:
    completed = set()

total = remaining = 0
with open(data_file) as f, open(remaining_file, 'w') as out:
    for line in f:
        if not line.strip(): continue
        total += 1
        try:
            r = json.loads(line)
            if r['instance_id'] not in completed:
                remaining += 1
                out.write(line)
        except Exception as e:
            print(f'  Warning: malformed source data line {total}: {e}')

print(f'  Total in dataset: {total}')
print(f'  Remaining left to solve: {remaining}')
"

    # Check if anything remains at all
    if [ ! -s $REMAINING_FILE ]; then
        echo ""
        echo "[$(date)] All 17k instances completed! Done."
        break
    fi

    # 3. THE FIX: Slice off just the next chunk of tasks
    echo "  Slicing next $CHUNK_SIZE tasks for execution..."
    head -n $CHUNK_SIZE $REMAINING_FILE >$CHUNK_FILE

    echo "[$(date)] Launching AweAgent on current chunk..."

    # Disable exit-on-error temporarily so single trajectory failures don't kill the loop
    set +e

    # Pass the CHUNK_FILE instead of the massive REMAINING_FILE
    python recipes/scale_swe/run.py \
        --data-file $CHUNK_FILE \
        --config $TASK_CONFIG \
        --llm-config $LLM_CONFIG \
        --mode batch \
        --max-concurrent $CONCURRENT \
        --output $OUTPUT_DIR

    # Re-enable exit-on-error
    set -e

    # THE RUTHLESS CLEANUP: Kill ANY container still running before we prune
    echo "[$(date)] Force-killing any rogue zombie containers..."
    # (Only do this if AweAgent is the ONLY thing using Docker on this machine!)
    docker rm -f $(docker ps -a -q) 2>/dev/null || true

    # Now clean up the dead volumes and caches
    echo "[$(date)] Purging dangling Docker storage caches on /tmp-tini..."
    docker system prune -f --volumes

    echo "[$(date)] Chunk finished. Checking the clock for the next cycle..."
    sleep 5
done
