#!/bin/bash

# --- CONFIGURATION ---
CGROUP_PATH="/sys/fs/cgroup/machine.slice"
CPU_RANGE="8-15"

# 1. Enable controllers in the ROOT & machine.slice
echo "+cpuset +cpu" | sudo tee /sys/fs/cgroup/cgroup.subtree_control > /dev/null
echo "+cpuset +cpu" | sudo tee "$CGROUP_PATH/cgroup.subtree_control" > /dev/null
#2. Enforce the cpuset controller for the machine.slice
echo "$CPU_RANGE" | sudo tee "$CGROUP_PATH/cpuset.cpus" > /dev/null
#3. Enforce the root partition to isolate the machine.slice cpuset
echo "root" | sudo tee "$CGROUP_PATH/cpuset.cpus.partition" > /dev/null
# --- VERIFICATION ---
FINAL_CPUS=$(cat "$CGROUP_PATH/cpuset.cpus.effective")
PARTITION_TYPE=$(cat "$CGROUP_PATH/cpuset.cpus.partition")

echo "------------------------------------------"
echo "Cgroup: $CGROUP_PATH"
echo "Effective Cores: $FINAL_CPUS"
echo "Partition Status: $PARTITION_TYPE"

if [ "$PARTITION_TYPE" == "root" ]; then
    echo "SUCCESS: Cores $CPU_RANGE are now isolated for your KLTN experiments."
else
    echo "WARNING: Partition is '$PARTITION_TYPE'. Isolation might be contested by other processes."
fi