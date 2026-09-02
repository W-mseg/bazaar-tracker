"""Entry point for the PyInstaller build (tracker/main.py can't be run
directly as a script since it uses relative imports)."""
from tracker.main import main

if __name__ == "__main__":
    main()
