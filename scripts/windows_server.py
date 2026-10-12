"""PyInstaller entry point for the W01-A simulated NiceGUI server."""
from chamber_web.windows_runtime import server_main

if __name__ == "__main__":
    raise SystemExit(server_main())
