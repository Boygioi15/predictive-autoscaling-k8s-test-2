#!/bin/bash

# 1. Restore CPU frequency scaling
# Using 'powersave' is correct for the intel_pstate driver on your Nitro
# Here, I use the E-core, each cpu from 10-15 is on its own computing core
sudo cpupower -c 10-15 frequency-set -d 400Mhz -u 3300Mhz -g powersave

# 2. Re-enable C-states (Sleep States)
for cpu in {10..15}; do
    for state in /sys/devices/system/cpu/cpu$cpu/cpuidle/state[1-9]; do
        if [ -d "$state" ]; then
            # '0' means 'Not Disabled' (Enabled)
            echo 0 | sudo tee "$state/disable" > /dev/null
        fi
    done
done

# echo "------------------------------------------"
# echo "Cores 10-15 restored to normal behavior."
# echo "Current frequency status:"
# cpupower -c 10-15 frequency-info | grep "energy performance preference"