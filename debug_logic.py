import subprocess
from pathlib import Path

# Mock simulation of the logic locally
def simulate_logic(height, vertical_pos):
    print(f"\n--- Simulation for Height={height}, Pos={vertical_pos} ---")
    margin_v = int((height / 2) + vertical_pos)
    print(f"Calculated MarginV: {margin_v}")
    
    # Check boundaries
    if margin_v < 0:
        print("WARNING: MarginV is negative! Text might be off-screen (below).")
    elif margin_v > height:
        print("WARNING: MarginV > Height! Text might be off-screen (above).")
    else:
        print("MarginV seems valid (on screen).")

simulate_logic(1920, -900)
simulate_logic(1920, 0)
