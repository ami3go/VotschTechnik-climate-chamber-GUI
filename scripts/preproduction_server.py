"""PyInstaller entry point for the FULL pre-production NiceGUI server."""
from chamber_web.desktop_runtime import server_main

if __name__ == "__main__":
    raise SystemExit(server_main())
