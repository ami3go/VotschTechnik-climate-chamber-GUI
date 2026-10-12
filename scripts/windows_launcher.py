"""PyInstaller entry point for the W01-A browser-only launcher."""
from chamber_web.windows_runtime import launcher_main

if __name__ == "__main__":
    raise SystemExit(launcher_main())
