#!/bin/bash

# 1. Lock Frequency for Cores 10 through 15
# -c 10-15 targets only your chosen research cores
sudo cpupower -c 10-15 frequency-set -u 2000MHz -d 2000MHz

# 2. Disable Sleep States (C-States) ONLY for Cores 10-15
# This prevents these specific cores from "napping" during your scaling tests
for cpu in {10..15}; do
    for state in /sys/devices/system/cpu/cpu$cpu/cpuidle/state[1-9]; do
        if [ -d "$state" ]; then
            echo 1 | sudo tee "$state/disable" > /dev/null
        fi
    done
done

# echo "Cores 10-15 are now locked at 2000MHz with C-States disabled."
# echo "Ready for isolated Minikube benchmarking!"