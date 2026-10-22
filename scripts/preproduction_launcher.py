"""PyInstaller entry point for the pre-production browser launcher."""
from chamber_web.desktop_runtime import launcher_main

if __name__ == "__main__":
    raise SystemExit(launcher_main())
