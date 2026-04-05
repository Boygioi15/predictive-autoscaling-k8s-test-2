import os
import math
import logging
from locust import LoadTestShape

logger = logging.getLogger(__name__)

class ScenarioShape(LoadTestShape):
    """
    A custom load test shape that supports multiple scenarios based on environment variables.
    
    SCENARIO=none
        Manual mode - no automatic load management. Control users via the Locust web UI.

    SCENARIO=idle
        IDLE_BASE_USERS (default: 50)
        IDLE_VARIATION (default: 10) - Jitter around base users
        IDLE_PERIOD_SEC (default: 60) - Time for a full variation cycle

    SCENARIO=spike
        SPIKE_BASE_USERS (default: 10)
        SPIKE_PEAK_USERS (default: 100)
        SPIKE_RAMPUP_MINS (default: 2)
        SPIKE_HOLD_PEAK_MINS (default: 3)
    
    SCENARIO=daily
        DAILY_BASE_USERS (default: 50)
        DAILY_VARIATION (default: 30) - Jitter around base users
        DAILY_PERIOD_SEC (default: 300) - Time for a full variation cycle
    
    SCENARIO=staircase
        STAIRCASE_BASE_USERS (default: 50)
        STAIRCASE_STEP_USERS (default: 10) - Users per step
        STAIRCASE_STEP_DUR_SEC (default: 30) - Duration of each step
    
    SCENARIO=playlist
        PLAYLIST_SCHEDULE (default: "idle:10,spike:5") - Comma-separated scenario:duration_mins
    """
    def __init__(self):
        super().__init__()
        
        # Read scenario and settings from environment
        self.scenario = os.getenv("SCENARIO", "idle").lower()
        # Idle scenario settings
        self.idle_base = int(os.getenv("IDLE_BASE_USERS", 50))
        self.idle_variation = int(os.getenv("IDLE_VARIATION", 10))
        self.idle_period = int(os.getenv("IDLE_PERIOD_SEC", 60))
        
        # Spike scenario settings
        self.spike_base = int(os.getenv("SPIKE_BASE_USERS", 10))
        self.spike_peak = int(os.getenv("SPIKE_PEAK_USERS", 100))
        spike_rampup_mins = float(os.getenv("SPIKE_RAMPUP_MINS", 2.0))
        spike_hold_mins = float(os.getenv("SPIKE_HOLD_PEAK_MINS", 3.0))
        
        self.spike_rampup_secs = spike_rampup_mins * 60
        self.spike_hold_secs = spike_hold_mins * 60

        # Daily scenario settings
        self.daily_base = int(os.getenv("DAILY_BASE_USERS", 50))
        self.daily_variation = int(os.getenv("DAILY_VARIATION", 30))
        self.daily_period = int(os.getenv("DAILY_PERIOD_SEC", 300))

        # Staircase scenario settings
        self.staircase_base = int(os.getenv("STAIRCASE_BASE_USERS", 50))
        self.staircase_step_users = int(os.getenv("STAIRCASE_STEP_USERS", 10))
        self.staircase_step_dur = int(os.getenv("STAIRCASE_STEP_DUR_SEC", 30))
        
        # Parse playlist schedule
        self.playlist = []
        schedule_str = os.getenv("PLAYLIST_SCHEDULE", "idle:10,spike:5")
        try:
            for item in schedule_str.split(','):
                parts = item.split(':')
                if len(parts) == 2:
                    self.playlist.append({
                        'scenario': parts[0].strip().lower(),
                        'duration_secs': float(parts[1].strip()) * 60
                    })
        except Exception as e:
            logger.error(f"Error parsing PLAYLIST_SCHEDULE: {e}")

    def tick(self):
        run_time = self.get_run_time()
        if self.scenario == "playlist":
            current_time = 0
            active_scenario = None
            scenario_run_time = 0
            
            for item in self.playlist:
                if run_time < current_time + item['duration_secs']:
                    active_scenario = item['scenario']
                    scenario_run_time = run_time - current_time
                    break
                current_time += item['duration_secs']
                
            if not active_scenario:
                # Playlist finished. Return None to stop the load test.
                return None
                
            return self.get_scenario_tick(active_scenario, scenario_run_time)
        else:
            return self.get_scenario_tick(self.scenario, run_time)

    def get_scenario_tick(self, scenario_name, run_time):
        if scenario_name == "none":
            # Manual mode: return None to disable automatic load management
            # Users can be controlled manually via the Locust web UI
            return None
            
        elif scenario_name == "idle":
            cycle_position = (run_time / max(self.idle_period, 1)) * 2 * math.pi
            user_count = int(self.idle_base + self.idle_variation * math.sin(cycle_position))
            user_count = max(0, user_count)
            spawn_rate = max(self.idle_variation / 5.0, 2.0)
            return (user_count, spawn_rate)
            
        elif scenario_name == "spike":
            if run_time < self.spike_rampup_secs:
                progress = run_time / max(self.spike_rampup_secs, 1.0)
                user_count = int(self.spike_base + (self.spike_peak - self.spike_base) * progress)
                spawn_rate = max((self.spike_peak - self.spike_base) / max(self.spike_rampup_secs, 1.0), 1.0)
                return (user_count, spawn_rate)
                
            elif run_time < self.spike_rampup_secs + self.spike_hold_secs:
                user_count = self.spike_peak
                spawn_rate = 5.0 
                return (user_count, spawn_rate)
                
            else:
                user_count = self.spike_base
                spawn_rate = 10.0
                return (user_count, spawn_rate)
                
        elif scenario_name == "daily":
            # Simple daily mock: large sine wave simulating day/night cycle
            cycle_position = (run_time / max(self.daily_period, 1)) * 2 * math.pi
            user_count = int(self.daily_base + self.daily_variation * math.sin(cycle_position))
            return (max(0, user_count), 5.0)
            
        elif scenario_name == "staircase":
            steps = int(run_time / max(self.staircase_step_dur, 1))
            user_count = self.staircase_base + (steps * self.staircase_step_users)
            return (user_count, 5.0)
            
        else:
            logger.warning(f"Unknown scenario: {scenario_name}. Defaulting to flat base users.")
            return (self.idle_base, 5.0)
