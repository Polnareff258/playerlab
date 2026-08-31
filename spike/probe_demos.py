"""Probe all SampleDemo files: map, rounds, size (quick header-only read)."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
from demoparser2 import DemoParser

demo_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "SampleDemo")
for name in sorted(os.listdir(demo_dir)):
    if not name.endswith(".dem"):
        continue
    path = os.path.join(demo_dir, name)
    t0 = time.time()
    try:
        parser = DemoParser(path)
        header = parser.parse_header()
        rounds = parser.parse_event("round_start")
        print(f"{name[:45]:<48} map={header.get('map_name'):<12} rounds={len(rounds):>3} "
              f"size={os.path.getsize(path)/1e6:.0f}MB probe={time.time()-t0:.1f}s")
    except Exception as e:
        print(f"{name[:45]:<48} ERROR {type(e).__name__}: {str(e)[:80]}")
