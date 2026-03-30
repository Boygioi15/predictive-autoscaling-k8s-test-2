#!/bin/bash

# --- CONFIGURATION ---
CGROUP_PATH="/sys/fs/cgroup/machine.slice"

echo "Releasing cpuset restrictions from $CGROUP_PATH..."

# 1. Disable the 'root' partition status first
# This is crucial. Setting it back to 'member' stops hardware-level isolation.
if [ -f "$CGROUP_PATH/cpuset.cpus.partition" ]; then
    echo "member" | sudo tee "$CGROUP_PATH/cpuset.cpus.partition" > /dev/null
fi

# 2. Reset the CPU range to all available cores
# By writing an empty string or the full range, you allow inheritance from root.
# On most systems, writing a blank value resets it to the parent's default.
echo "" | sudo tee "$CGROUP_PATH/cpuset.cpus" > /dev/null

# 3. (Optional) Disable the controller in subtree_control 
# Only do this if you want to stop child groups (like libvirt) from managing cpusets.
echo "-cpuset" | sudo tee "$CGROUP_PATH/cgroup.subtree_control" > /dev/null

# --- VERIFICATION ---
FINAL_CPUS=$(cat "$CGROUP_PATH/cpuset.cpus.effective")
PARTITION_TYPE=$(cat "$CGROUP_PATH/cpuset.cpus.partition")

echo "------------------------------------------"
echo "Cgroup: $CGROUP_PATH"
echo "Effective Cores: $FINAL_CPUS (Should match system total)"
echo "Partition Status: $PARTITION_TYPE (Should be 'member')"

if [ "$PARTITION_TYPE" == "member" ]; then
    echo "SUCCESS: Cores are released. machine.slice can now use all system CPUs."
else
    echo "ERROR: Failed to release partition status."
fi

