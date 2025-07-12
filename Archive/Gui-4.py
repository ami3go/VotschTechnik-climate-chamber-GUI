import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GObject, GLib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_gtk3agg import FigureCanvasGTK3Agg as FigureCanvas
import random

# Dummy class for the chamber interface
class ClimateChamber:
    def __init__(self, ip, temperature_min=-40, temperature_max=85):
        self.ip = ip
        self.temperature_measured = 25.0
        self.temperature_set_point = 25.0
        self.running = False

    def start_execution(self):
        self.running = True
        return True

    def stop_execution(self):
        self.running = False
        return True

    def retrieve_climate_chamber_status(self):
        # Simulate sensor reading
        if self.running:
            self.temperature_measured += random.uniform(-0.5, 0.5)

# GUI class
class ThermalChamberGUI(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, title="Thermal Chamber Controller")
        self.set_border_width(10)
        self.set_default_size(900, 600)

        self.chamber = None
        self.current_temperature = 25.0
        self.temperature_history = [self.current_temperature]
        self.time = [0]
        self.running = False

        self.build_ui()

        # Start temperature update timer
        GObject.timeout_add(1000, self.update_temperature)

    def build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(main_box)

        # IP + Connect
        ip_box = Gtk.Box(spacing=10)
        main_box.pack_start(ip_box, False, False, 0)

        self.ip_store = Gtk.ListStore(str)
        for ip in ["192.168.0.100", "192.168.0.101", "192.168.0.102"]:
            self.ip_store.append([ip])

        self.ip_combo = Gtk.ComboBox.new_with_model_and_entry(self.ip_store)
        self.ip_combo.set_entry_text_column(0)
        ip_box.pack_start(self.ip_combo, True, True, 0)

        self.connect_btn = Gtk.Button(label="Connect")
        self.connect_btn.connect("clicked", self.connect_chamber)
        ip_box.pack_start(self.connect_btn, False, False, 0)

        self.disconnect_btn = Gtk.Button(label="Disconnect")
        self.disconnect_btn.set_sensitive(False)
        self.disconnect_btn.connect("clicked", self.disconnect_chamber)
        ip_box.pack_start(self.disconnect_btn, False, False, 0)

        # Temp buttons
        temp_box = Gtk.Box(spacing=10)
        main_box.pack_start(temp_box, False, False, 0)

        for t in (-40, 25, 60, 85):
            btn = Gtk.Button(label=f"{t}°C")
            btn.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(*self.get_color_for_temp(t)))
            btn.connect("clicked", self.set_temperature, t)
            temp_box.pack_start(btn, True, True, 0)

        self.custom_entry = Gtk.Entry()
        self.custom_entry.set_placeholder_text("Custom Temp")
        temp_box.pack_start(self.custom_entry, False, False, 0)

        set_btn = Gtk.Button(label="Set Custom")
        set_btn.connect("clicked", self.set_custom_temperature)
        temp_box.pack_start(set_btn, False, False, 0)

        # Run / Stop / Close
        action_box = Gtk.Box(spacing=10)
        main_box.pack_start(action_box, False, False, 0)

        self.run_btn = Gtk.Button(label="Run Chamber")
        self.run_btn.connect("clicked", self.run_chamber)
        self.run_btn.set_sensitive(False)
        action_box.pack_start(self.run_btn, False, False, 0)

        self.stop_btn = Gtk.Button(label="Stop Chamber")
        self.stop_btn.connect("clicked", self.stop_chamber)
        self.stop_btn.set_sensitive(False)
        action_box.pack_start(self.stop_btn, False, False, 0)

        close_btn = Gtk.Button(label="Close Application")
        close_btn.connect("clicked", Gtk.main_quit)
        action_box.pack_start(close_btn, False, False, 0)

        # Temp Display
        self.temp_label = Gtk.Label(label="Current Temp: 25.0°C")
        main_box.pack_start(self.temp_label, False, False, 0)

        # Plot Area
        self.fig, self.ax = plt.subplots()
        self.line, = self.ax.plot(self.time, self.temperature_history, label="Temp")
        self.ax.set_title("Temperature Over Time")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Temperature (°C)")
        self.ax.grid(True)

        self.canvas = FigureCanvas(self.fig)
        main_box.pack_start(self.canvas, True, True, 0)

    def get_color_for_temp(self, temp, t_min=-40, t_max=85):
        ratio = (temp - t_min) / (t_max - t_min)
        ratio = max(0, min(1, ratio))
        r = 0.13 + (0.96 - 0.13) * ratio
        g = 0.59 + (0.26 - 0.59) * ratio
        b = 0.95 + (0.21 - 0.95) * ratio
        return r, g, b, 1.0  # RGBA

    def connect_chamber(self, button):
        tree_iter = self.ip_combo.get_active_iter()
        if tree_iter is not None:
            model = self.ip_combo.get_model()
            ip = model[tree_iter][0]
            self.chamber = ClimateChamber(ip)
            self.disconnect_btn.set_sensitive(True)
            self.run_btn.set_sensitive(True)
            self.stop_btn.set_sensitive(True)

    def disconnect_chamber(self, button):
        if self.chamber:
            self.chamber.stop_execution()
        self.chamber = None
        self.disconnect_btn.set_sensitive(False)
        self.run_btn.set_sensitive(False)
        self.stop_btn.set_sensitive(False)
        self.temp_label.set_text("Current Temp: -- °C")

    def set_temperature(self, button, temp):
        if self.chamber:
            self.chamber.temperature_set_point = temp

    def set_custom_temperature(self, button):
        try:
            val = float(self.custom_entry.get_text())
            self.set_temperature(button, val)
        except ValueError:
            print("Invalid number")

    def run_chamber(self, button):
        if self.chamber:
            self.chamber.start_execution()
            self.running = True
            self.run_btn.override_background_color(Gtk.StateFlags.NORMAL, Gdk.RGBA(0.27, 0.75, 0.34, 1.0))  # Green

    def stop_chamber(self, button):
        if self.chamber:
            self.chamber.stop_execution()
            self.running = False
            self.run_btn.override_background_color(Gtk.StateFlags.NORMAL, None)

    def update_temperature(self):
        if self.chamber and self.chamber.running:
            self.chamber.retrieve_climate_chamber_status()
            temp = self.chamber.temperature_measured
            self.temperature_history.append(temp)
            self.time.append(len(self.time))
            self.temp_label.set_text(f"Current Temp: {temp:.1f}°C")

            # Trim data
            if len(self.time) > 100:
                self.time = self.time[-100:]
                self.temperature_history = self.temperature_history[-100:]

            self.line.set_data(self.time, self.temperature_history)
            self.ax.set_xlim(self.time[0], self.time[-1])
            self.ax.set_ylim(min(self.temperature_history)-5, max(self.temperature_history)+5)
            self.canvas.draw()
        return True  # keep calling this function

# Import after GTK to avoid init conflicts
from gi.repository import Gdk

win = ThermalChamberGUI()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
