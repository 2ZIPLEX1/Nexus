"""
Launch Steam Trading Bot GUI without console window.
Double-click this file to run the GUI.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import and run
from flet_gui.main import main

if __name__ == "__main__":
    # Run with real data by default
    sys.argv = ["run_gui.pyw", "--real-data"]
    main()
