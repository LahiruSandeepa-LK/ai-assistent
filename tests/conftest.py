import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBS = os.path.join(ROOT, "libs")
if LIBS not in sys.path:
    sys.path.insert(0, LIBS)
