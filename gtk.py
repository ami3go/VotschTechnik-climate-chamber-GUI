import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_gtk3agg import FigureCanvasGTK3Agg as FigureCanvas
import numpy as np
import threading
import time
import random

# Define color scheme for Android-like UI
COLORS = {
    'background': '#f5f5f5',
    'header': '#3f51b5',
    'button_primary': '#4caf50',
    'button_danger': '#f44336',
    'button_warning': '#ff9800',
    'button_info': '#2196f3',
    'card': '#ffffff',
    'text_primary': '#212121',
    'text_secondary': '#757575',
    'status_running': '#4caf50',
    'status_stopped': '#f44336',
    'temp_display': '#2196f3',
    'target_display': '#4caf50',
}


class ThermalChamberController(Gtk.Window):
    def __init__(self):
        super().__init__(title="Thermal Chamber Controller")
        self.set_default_size(800, 700)
        self.set_resizable(True)

        # Apply custom CSS for styling
        self.apply_styles()

        # Setup main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(main_box)

        # Create header bar
        self.create_header_bar(main_box)

        # Create content area
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content_box.set_margin_top(10)
        content_box.set_margin_bottom(10)
        content_box.set_margin_start(10)
        content_box.set_margin_end(10)
        main_box.pack_start(content_box, True, True, 0)

        # Create status and temperature displays
        self.create_status_area(content_box)

        # Create temperature controls
        self.create_temp_controls(content_box)

        # Create plot area
        self.create_plot_area(content_box)

        # Initialize variables
        self.current_temp = 25.0
        self.target_temp = 25.0
        self.is_running = False
        self.chamber_ip = "192.168.1.100"
        self.running = True

        # Setup plot
        self.setup_plot()

        # Start temperature simulation thread
        self.simulation_thread = threading.Thread(target=self.simulate_temperature)
        self.simulation_thread.daemon = True
        self.simulation_thread.start()

        # Connect delete event
        self.connect("delete-event", self.on_delete_event)

    def apply_styles(self):
        screen = Gdk.Screen.get_default()
        css_provider = Gtk.CssProvider()
        css = f"""
        * {{
            font-family: 'Roboto', sans-serif;
        }}

        window {{
            background-color: {COLORS['background']};
        }}

        .header {{
            background-color: {COLORS['header']};
            color: white;
            padding: 15px;
            font-size: 18px;
            font-weight: bold;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .card {{
            background-color: {COLORS['card']};
            border-radius: 8px;
            padding: 15px;
            margin: 5px 0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}

        .temp-display {{
            font-size: 24px;
            font-weight: bold;
            color: {COLORS['temp_display']};
            padding: 5px 0;
        }}

        .target-display {{
            font-size: 24px;
            font-weight: bold;
            color: {COLORS['target_display']};
            padding: 5px 0;
        }}

        .status-label {{
            font-size: 14px;
            padding: 5px 10px;
            border-radius: 12px;
            color: white;
        }}

        .button {{
            border: none;
            border-radius: 4px;
            padding: 8px 16px;
            font-weight: bold;
            color: white;
            transition: all 0.3s;
        }}

        .button:hover {{
            opacity: 0.9;
        }}

        .button:active {{
            transform: scale(0.98);
        }}

        .button-primary {{
            background-color: {COLORS['button_primary']};
        }}

        .button-danger {{
            background-color: {COLORS['button_danger']};
        }}

        .button-warning {{
            background-color: {COLORS['button_warning']};
        }}

        .button-info {{
            background-color: {COLORS['button_info']};
        }}

        .preset-button {{
            padding: 10px 0;
            font-size: 16px;
        }}

        .ip-combo {{
            border-radius: 4px;
            padding: 6px;
            background-color: white;
        }}
        """
        # css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def create_header_bar(self, parent):
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        header_box.get_style_context().add_class("header")
        parent.pack_start(header_box, False, False, 0)

        title_label = Gtk.Label(label="THERMAL CHAMBER CONTROLLER")
        header_box.pack_start(title_label, True, True, 0)

        # IP selection
        ip_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        header_box.pack_end(ip_box, False, False, 0)

        ip_label = Gtk.Label(label="Chamber IP:")
        ip_box.pack_start(ip_label, False, False, 0)

        self.ip_combo = Gtk.ComboBoxText()
        self.ip_combo.get_style_context().add_class("ip-combo")
        for ip in ["192.168.1.100", "192.168.1.101", "192.168.1.102", "10.0.0.50"]:
            self.ip_combo.append_text(ip)
        self.ip_combo.set_active(0)
        self.ip_combo.connect("changed", self.on_ip_changed)
        ip_box.pack_start(self.ip_combo, False, False, 0)

    def create_status_area(self, parent):
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        status_box.get_style_context().add_class("card")
        parent.pack_start(status_box, False, False, 0)

        # Status indicator
        status_container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        status_box.pack_start(status_container, True, True, 0)

        status_label = Gtk.Label(label="Status:")
        status_container.pack_start(status_label, False, False, 0)

        self.status_indicator = Gtk.Label(label="STOPPED")
        self.status_indicator.get_style_context().add_class("status-label")
        self.status_indicator.get_style_context().add_class("button-danger")
        status_container.pack_start(self.status_indicator, False, False, 0)

        # Temperature displays
        temp_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        status_box.pack_end(temp_box, False, False, 0)

        current_temp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        temp_box.pack_start(current_temp_box, False, False, 0)

        current_label = Gtk.Label(label="Current Temperature")
        current_temp_box.pack_start(current_label, False, False, 0)

        self.current_temp_label = Gtk.Label(label="25.0 °C")
        self.current_temp_label.get_style_context().add_class("temp-display")
        current_temp_box.pack_start(self.current_temp_label, False, False, 0)

        target_temp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        temp_box.pack_start(target_temp_box, False, False, 0)

        target_label = Gtk.Label(label="Target Temperature")
        target_temp_box.pack_start(target_label, False, False, 0)

        self.target_temp_label = Gtk.Label(label="25.0 °C")
        self.target_temp_label.get_style_context().add_class("target-display")
        target_temp_box.pack_start(self.target_temp_label, False, False, 0)

    def create_temp_controls(self, parent):
        # Preset buttons
        preset_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        preset_box.get_style_context().add_class("card")
        parent.pack_start(preset_box, False, False, 0)

        preset_label = Gtk.Label(label="Preset Temperatures:")
        preset_box.pack_start(preset_label, False, False, 0)

        # Create preset buttons
        self.create_preset_button(preset_box, "-40°C", self.set_temp_minus_40, "button-info")
        self.create_preset_button(preset_box, "+25°C", self.set_temp_25, "button-primary")
        self.create_preset_button(preset_box, "+60°C", self.set_temp_60, "button-warning")
        self.create_preset_button(preset_box, "+85°C", self.set_temp_85, "button-danger")

        # Custom temperature control
        custom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        custom_box.get_style_context().add_class("card")
        parent.pack_start(custom_box, False, False, 0)

        custom_label = Gtk.Label(label="Custom Temperature:")
        custom_box.pack_start(custom_label, False, False, 0)

        # Scale for temperature selection
        self.temp_scale = Gtk.Scale.new_with_range(
            orientation=Gtk.Orientation.HORIZONTAL,
            min=-40,
            max=150,
            step=1
        )
        self.temp_scale.set_value(25)
        self.temp_scale.set_hexpand(True)
        self.temp_scale.set_draw_value(True)
        custom_box.pack_start(self.temp_scale, True, True, 0)

        # Set custom temperature button
        custom_button = Gtk.Button(label="Set Custom")
        custom_button.get_style_context().add_class("button")
        custom_button.get_style_context().add_class("button-primary")
        custom_button.connect("clicked", self.on_set_custom_temp)
        custom_box.pack_start(custom_button, False, False, 10)

        # Control buttons
        control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        control_box.get_style_context().add_class("card")
        parent.pack_start(control_box, False, False, 0)

        # Start button
        self.start_button = Gtk.Button(label="START CHAMBER")
        self.start_button.get_style_context().add_class("button")
        self.start_button.get_style_context().add_class("button-primary")
        self.start_button.set_size_request(200, 50)
        self.start_button.connect("clicked", self.on_start_chamber)
        control_box.pack_start(self.start_button, True, True, 0)

        # Stop button
        self.stop_button = Gtk.Button(label="STOP CHAMBER")
        self.stop_button.get_style_context().add_class("button")
        self.stop_button.get_style_context().add_class("button-danger")
        self.stop_button.set_size_request(200, 50)
        self.stop_button.connect("clicked", self.on_stop_chamber)
        self.stop_button.set_sensitive(False)
        control_box.pack_start(self.stop_button, True, True, 0)

    def create_plot_area(self, parent):
        plot_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        plot_box.get_style_context().add_class("card")
        plot_box.set_hexpand(True)
        plot_box.set_vexpand(True)
        parent.pack_start(plot_box, True, True, 0)

        plot_label = Gtk.Label(label="Temperature Profile")
        plot_label.set_margin_bottom(10)
        plot_box.pack_start(plot_label, False, False, 0)

        # Create container for the plot
        self.plot_container = Gtk.Box()
        plot_box.pack_start(self.plot_container, True, True, 0)

    def setup_plot(self):
        # Create figure for plotting
        self.fig, self.ax = plt.subplots(figsize=(6, 4), dpi=80)
        self.fig.patch.set_facecolor('#FFFFFF')
        self.ax.set_facecolor('#f8f9fa')

        # Customize plot appearance
        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.ax.set_xlabel('Time (minutes)')
        self.ax.set_ylabel('Temperature (°C)')
        self.ax.set_title('Temperature Profile', fontsize=12)
        self.ax.set_ylim(-50, 100)

        # Create initial empty data
        self.x_data = []
        self.y_data = []
        self.line, = self.ax.plot([], [], 'b-', linewidth=2)

        # Create the canvas and add to container
        self.canvas = FigureCanvas(self.fig)
        self.plot_container.pack_start(self.canvas, True, True, 0)
        self.canvas.set_size_request(-1, 300)

    def create_preset_button(self, parent, label, callback, style_class):
        button = Gtk.Button(label=label)
        button.get_style_context().add_class("button")
        button.get_style_context().add_class(style_class)
        button.get_style_context().add_class("preset-button")
        button.connect("clicked", callback)
        parent.pack_start(button, True, True, 0)

    def on_ip_changed(self, combo):
        self.chamber_ip = combo.get_active_text()
        print(f"Chamber IP set to: {self.chamber_ip}")

    def set_temp(self, temp):
        self.target_temp = temp
        self.target_temp_label.set_text(f"{self.target_temp:.1f} °C")
        self.temp_scale.set_value(temp)

    def set_temp_minus_40(self, button):
        self.set_temp(-40)

    def set_temp_25(self, button):
        self.set_temp(25)

    def set_temp_60(self, button):
        self.set_temp(60)

    def set_temp_85(self, button):
        self.set_temp(85)

    def on_set_custom_temp(self, button):
        self.set_temp(self.temp_scale.get_value())

    def on_start_chamber(self, button):
        self.is_running = True
        self.status_indicator.set_text("RUNNING")
        self.status_indicator.get_style_context().remove_class("button-danger")
        self.status_indicator.get_style_context().add_class("button-primary")
        self.start_button.set_sensitive(False)
        self.stop_button.set_sensitive(True)

    def on_stop_chamber(self, button):
        self.is_running = False
        self.status_indicator.set_text("STOPPED")
        self.status_indicator.get_style_context().remove_class("button-primary")
        self.status_indicator.get_style_context().add_class("button-danger")
        self.start_button.set_sensitive(True)
        self.stop_button.set_sensitive(False)

    def simulate_temperature(self):
        # Temperature simulation thread
        start_time = time.time()
        while self.running:
            # Add new data point every second
            elapsed_minutes = (time.time() - start_time) / 60
            self.x_data.append(elapsed_minutes)

            # Simulate temperature change toward target
            if self.is_running:
                diff = self.target_temp - self.current_temp
                step = diff * 0.05 + random.uniform(-0.1, 0.1)
                self.current_temp += step
            else:
                # Slowly drift toward room temperature
                self.current_temp += (25 - self.current_temp) * 0.01 + random.uniform(-0.05, 0.05)

            self.y_data.append(self.current_temp)

            # Keep only the last 100 points
            if len(self.x_data) > 100:
                self.x_data = self.x_data[-100:]
                self.y_data = self.y_data[-100:]

            # Update display on main thread
            GLib.idle_add(self.update_display)

            time.sleep(0.5)

    def update_display(self):
        # Update temperature display
        self.current_temp_label.set_text(f"{self.current_temp:.1f} °C")

        # Update plot
        self.line.set_data(self.x_data, self.y_data)

        # Adjust plot limits
        if len(self.x_data) > 0:
            self.ax.set_xlim(0, max(self.x_data) + 0.5)

        # Redraw the plot
        self.canvas.draw_idle()

    def on_delete_event(self, widget, event):
        self.running = False
        Gtk.main_quit()


if __name__ == "__main__":
    win = ThermalChamberController()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()