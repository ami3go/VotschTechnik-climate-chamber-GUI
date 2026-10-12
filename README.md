# Vötsch Climate Chamber Control

## New NiceGUI web interface (simulation scaffold)

The new browser-based interface is being developed in `chamber_web/`, based on the supplied Visteon-themed dashboard concept. It provides a responsive dashboard, editable temperature profile, simulated test sequence, chart, and profile CSV import/export.

**Safety:** The web scaffold is a DEMO only. It does not communicate with chamber hardware. Real device control will use the separate [Python driver](https://github.com/ami3go/VotschTechnik-climate-chamber-Python) in a later, tested integration. See [web setup and current limitations](README_WEB.md) and the [migration plan](https://github.com/ami3go/VotschTechnik-climate-chamber-GUI/pull/3).

Start locally with `python -m pip install -r requirements-web.txt` and `python main.py` (visit http://127.0.0.1:8080).

---

## Legacy Tkinter desktop GUI

 ![image](/pictures/main-tab.png)

Executable file for windows is available [here](/dist/)

Old chambers frequently have broken touch, which don't allow to operate chamber. 

Original software also frequently give an error. 

This simple gui may be used to bypass original software, or create a touch screen based on raspbery Pi

Software tested with VT4011
 
Communication protocol based on https://github.com/ami3go/VotschTechnik-climate-chamber-Python - (fork from [this project](https://github.com/SengerM/VotschTechnik-climate-chamber-Python))

Features: 
* start and stop chamber
* Set temperature, read current temperature 

Features to be impemented:
* Temperature profile from table or csv file 

