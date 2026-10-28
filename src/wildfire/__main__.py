"""Run the pipeline: python -m wildfire [step ...]

Steps run in order. Name steps to run only those, e.g. `python -m wildfire evaluate analyze`.
Downloading is separate (python -m wildfire.download) because it only needs to happen once.
"""
import sys
import time
import warnings

from wildfire import analyze, clean, evaluate, features, figures, ingest, join, outputs, spotcheck

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

STEPS = {
    "ingest": ingest.main,
    "clean": clean.main,
    "join": join.main,
    "features": features.main,
    "evaluate": evaluate.main,
    "analyze": analyze.main,
    "outputs": outputs.main,
    "figures": figures.main,
    "spotcheck": spotcheck.main,
}


def main(argv):
    unknown = set(argv) - set(STEPS)
    if unknown:
        sys.exit(f"unknown steps: {', '.join(sorted(unknown))}. Choose from {', '.join(STEPS)}")
    start = time.time()
    for name, fn in STEPS.items():
        if argv and name not in argv:
            continue
        t = time.time()
        print(name)
        fn()
        print(f"  ({time.time() - t:.0f}s)")
    print(f"done in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main(sys.argv[1:])
