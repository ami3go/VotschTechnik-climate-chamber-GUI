import tkinter as tk
from tkinter import ttk, messagebox, Scale  # Added Scale here
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
from threading import Thread, Event
import time
import random
from colorsys import hsv_to_rgb
import queue
import socket


class ThermalChamberController:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced Thermal Chamber Controller")
        self.root.geometry("1200x800")

        # Configuration
        self.config = {
            'min_temp': -40,
            'max_temp': 150,
            'update_interval': 0.5,  # seconds
            'max_data_points': 300,
            'simulation_speed': 0.05,
            'default_ip': "192.168.1.100",
            'port': 5025  # Standard SCPI port
        }

        # State variables
        self.current_temp = 25.0
        self.target_temp = 25.0
        self.is_running = False
        self.is_connected = False
        self._shutdown_event = Event()
        self.command_queue = queue.Queue()

        # Initialize UI
        # self.setup_theme()
        self.create_widgets()
        self.setup_plot()
        self.create_serial_number_window()

        # Start threads
        self.start_threads()

        # Load default settings
        self.load_settings()

    # [Rest of the class implementation remains exactly the same]
    # ... all other methods unchanged ...


if __name__ == "__main__":
    root = tk.Tk()
    app = ThermalChamberController(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

class ThermalChamberController:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced Thermal Chamber Controller")
        self.root.geometry("1200x800")

        # Configuration
        self.config = {
            'min_temp': -40,
            'max_temp': 150,
            'update_interval': 0.5,  # seconds
            'max_data_points': 300,
            'simulation_speed': 0.05,
            'default_ip': "192.168.1.100",
            'port': 5025  # Standard SCPI port
        }

        # State variables
        self.current_temp = 25.0
        self.target_temp = 25.0
        self.is_running = False
        self.is_connected = False
        self._shutdown_event = Event()
        self.command_queue = queue.Queue()

        # Initialize UI
        self.setup_theme()
        self.create_widgets()
        self.setup_plot()
        self.create_serial_number_window()  # Add serial number window

        # Start threads
        self.start_threads()

        # Load default settings
        self.load_settings()

    def setup_theme(self):
        """Configure the application theme and colors"""
        self.style = ttk.Style()
        self.style.theme_use('clam')

        # Color scheme
        self.colors = {
            'bg': '#121212',
            'card': '#1E1E1E',
            'text': '#FFFFFF',
            'accent': '#4A6FA5',
            'warning': '#FFA726',
            'error': '#F44336',
            'success': '#4CAF50'
        }

        # Configure styles
        self.style.configure('TFrame', background=self.colors['bg'])
        self.style.configure('TLabel', background=self.colors['bg'], foreground=self.colors['text'])
        self.style.configure('Header.TLabel',
                             background=self.get_temp_color(25),
                             foreground='white',
                             font=('Helvetica', 16, 'bold'),
                             padding=10)
        self.style.configure('Card.TFrame', background=self.colors['card'], relief='flat', borderwidth=0)
        self.style.configure('Temp.TLabel',
                             background=self.colors['card'],
                             foreground=self.colors['text'],
                             font=('Helvetica', 24, 'bold'),
                             padding=10)
        self.style.configure('Status.TLabel',
                             background=self.get_temp_color(25),
                             foreground='white',
                             font=('Helvetica', 12),
                             padding=5,
                             borderwidth=0,
                             relief='flat')
        self.style.configure('TEntry',
                             fieldbackground=self.colors['card'],
                             foreground=self.colors['text'],
                             insertcolor=self.colors['text'],
                             borderwidth=1,
                             relief='flat')
        self.style.configure('TButton',
                             background=self.colors['card'],
                             foreground=self.colors['text'],
                             borderwidth=1,
                             relief='flat')
        self.style.map('TButton',
                       background=[('active', self.colors['accent'])])

    def create_widgets(self):
        """Create and arrange all UI widgets"""
        # Main container
        self.main_frame = ttk.Frame(self.root, style='TFrame')
        self.main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Header
        self.create_header()

        # Connection panel
        self.create_connection_panel()

        # Temperature display
        self.create_temp_display()

        # Preset buttons
        self.create_preset_buttons()

        # Temperature control
        self.create_temp_control()

        # Chamber controls
        self.create_chamber_controls()

        # Plot area
        self.create_plot_area()

        # Status bar
        self.create_status_bar()

    def create_serial_number_window(self):
        """Create the serial number display window (hidden by default)"""
        self.serial_window = tk.Toplevel(self.root)
        self.serial_window.title("Chamber Information")
        self.serial_window.geometry("300x200")
        self.serial_window.withdraw()  # Start hidden
        self.serial_window.protocol("WM_DELETE_WINDOW", self.hide_serial_window)

        # Style the window
        self.serial_window.configure(bg=self.colors['bg'])
        self.serial_window.resizable(False, False)

        # Add content
        content_frame = ttk.Frame(self.serial_window, style='Card.TFrame')
        content_frame.pack(fill='both', expand=True, padx=10, pady=10)

        ttk.Label(content_frame,
                  text="Thermal Chamber Information",
                  font=('Helvetica', 12, 'bold')).pack(pady=(5, 15))

        # Device information labels
        info_frame = ttk.Frame(content_frame)
        info_frame.pack(fill='x', pady=5)

        ttk.Label(info_frame, text="Manufacturer:", width=12, anchor='e').pack(side='left')
        self.manufacturer_label = ttk.Label(info_frame, text="Not Connected")
        self.manufacturer_label.pack(side='left', padx=5)

        ttk.Label(info_frame, text="Model:", width=12, anchor='e').pack(side='left')
        self.model_label = ttk.Label(info_frame, text="Not Connected")
        self.model_label.pack(side='left', padx=5)

        ttk.Label(info_frame, text="Serial Number:", width=12, anchor='e').pack(side='left')
        self.serial_label = ttk.Label(info_frame, text="Not Connected")
        self.serial_label.pack(side='left', padx=5)

        ttk.Label(info_frame, text="Firmware:", width=12, anchor='e').pack(side='left')
        self.firmware_label = ttk.Label(info_frame, text="Not Connected")
        self.firmware_label.pack(side='left', padx=5)

        # Close button
        ttk.Button(content_frame,
                   text="Close",
                   command=self.hide_serial_window).pack(pady=10)

    def show_serial_window(self):
        """Show the serial number window"""
        if hasattr(self, 'serial_window'):
            self.serial_window.deiconify()
            self.serial_window.lift()

    def hide_serial_window(self):
        """Hide the serial number window"""
        if hasattr(self, 'serial_window'):
            self.serial_window.withdraw()

    def update_device_info(self, info):
        """Update the device information display"""
        if hasattr(self, 'serial_window'):
            self.manufacturer_label.config(text=info.get('manufacturer', 'Unknown'))
            self.model_label.config(text=info.get('model', 'Unknown'))
            self.serial_label.config(text=info.get('serial', 'Unknown'))
            self.firmware_label.config(text=info.get('firmware', 'Unknown'))

    def create_header(self):
        """Create the header section"""
        self.header_frame = ttk.Frame(self.main_frame, style='Header.TFrame')
        self.header_frame.pack(fill='x', pady=(0, 10))

        self.header_label = ttk.Label(
            self.header_frame,
            text="ADVANCED THERMAL CHAMBER CONTROLLER",
            style='Header.TLabel'
        )
        self.header_label.pack(fill='x')

    def create_connection_panel(self):
        """Create the connection control panel"""
        self.connection_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.connection_frame.pack(fill='x', pady=5, padx=5)

        # IP selection
        ip_frame = ttk.Frame(self.connection_frame, style='Card.TFrame')
        ip_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(ip_frame, text="Chamber IP:", font=('Helvetica', 11)).pack(side='left', padx=(0, 5))

        self.ip_var = tk.StringVar(value=self.config['default_ip'])
        self.ip_combobox = ttk.Combobox(
            ip_frame,
            textvariable=self.ip_var,
            values=[
                "192.168.1.100",
                "192.168.1.101",
                "192.168.1.102",
                "10.0.0.50",
                "localhost"
            ],
            font=('Helvetica', 10),
            width=15
        )
        self.ip_combobox.pack(side='left', padx=(0, 5))

        # Connection buttons
        self.connect_button = ttk.Button(
            ip_frame,
            text="Connect",
            command=self.connect_chamber,
            style='TButton'
        )
        self.connect_button.pack(side='left', padx=5)

        self.disconnect_button = ttk.Button(
            ip_frame,
            text="Disconnect",
            command=self.disconnect_chamber,
            style='TButton',
            state='disabled'
        )
        self.disconnect_button.pack(side='left', padx=5)

        # Info button
        self.info_button = ttk.Button(
            ip_frame,
            text="Chamber Info",
            command=self.show_serial_window,
            style='TButton'
        )
        self.info_button.pack(side='left', padx=5)

        # Status indicator
        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(
            ip_frame,
            textvariable=self.status_var,
            style='Status.TLabel'
        )
        self.status_label.pack(side='right', padx=(0, 5))

    def create_temp_display(self):
        """Create temperature display widgets"""
        self.temp_display_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.temp_display_frame.pack(fill='x', pady=5, padx=5)

        # Current temperature
        current_frame = ttk.Frame(self.temp_display_frame, style='Card.TFrame')
        current_frame.pack(side='left', fill='x', expand=True, padx=10, pady=10)

        ttk.Label(current_frame, text="Current Temperature:", font=('Helvetica', 12)).pack(anchor='w')

        self.temp_var = tk.StringVar(value="25.0 °C")
        self.temp_label = ttk.Label(
            current_frame,
            textvariable=self.temp_var,
            style='Temp.TLabel'
        )
        self.temp_label.pack(fill='x', pady=5)

        # Target temperature
        target_frame = ttk.Frame(self.temp_display_frame, style='Card.TFrame')
        target_frame.pack(side='right', fill='x', expand=True, padx=10, pady=10)

        ttk.Label(target_frame, text="Target Temperature:", font=('Helvetica', 12)).pack(anchor='w')

        self.target_var = tk.StringVar(value="25.0 °C")
        self.target_label = ttk.Label(
            target_frame,
            textvariable=self.target_var,
            style='Temp.TLabel'
        )
        self.target_label.pack(fill='x', pady=5)

    def create_preset_buttons(self):
        """Create preset temperature buttons"""
        self.preset_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.preset_frame.pack(fill='x', pady=5, padx=5)

        ttk.Label(
            self.preset_frame,
            text="Preset Temperatures:",
            font=('Helvetica', 12)
        ).pack(anchor='w', padx=10, pady=(10, 5))

        button_frame = ttk.Frame(self.preset_frame, style='Card.TFrame')
        button_frame.pack(fill='x', padx=10, pady=(0, 10))

        preset_temps = [-40, -30, -20, 0, 25, 50, 75, 100, 125, 150]
        for temp in preset_temps:
            self.create_preset_button(
                button_frame,
                f"{temp}°C",
                lambda t=temp: self.set_temp(t),
                self.get_temp_color(temp)
            )

    def create_temp_control(self):
        """Create temperature control widgets"""
        self.temp_control_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.temp_control_frame.pack(fill='x', pady=10, padx=10)

        ttk.Label(
            self.temp_control_frame,
            text="Custom Temperature:",
            font=('Helvetica', 12)
        ).pack(anchor='w', padx=10, pady=(10, 5))

        control_frame = ttk.Frame(self.temp_control_frame, style='Card.TFrame')
        control_frame.pack(fill='x', padx=10, pady=(0, 10))

        # Temperature entry
        self.temp_entry = ttk.Entry(
            control_frame,
            font=('Helvetica', 10),
            width=8,
            style='TEntry'
        )
        self.temp_entry.insert(0, "25.0")
        self.temp_entry.pack(side='left', padx=(0, 20))
        self.temp_entry.bind('<Return>', self.on_temp_entry)

        # Set button for entry
        self.entry_button = ttk.Button(
            control_frame,
            text="Set",
            command=self.on_temp_entry,
            style='TButton'
        )
        self.entry_button.pack(side='left', padx=(0, 10))

        # Temperature slider
        self.custom_temp = tk.DoubleVar(value=25.0)
        self.custom_slider = Scale(
            control_frame,
            from_=self.config['min_temp'],
            to=self.config['max_temp'],
            orient="horizontal",
            variable=self.custom_temp,
            bg=self.colors['card'],
            fg=self.colors['text'],
            highlightthickness=0,
            troughcolor='#333333',
            length=400,
            command=self.on_slider_move
        )
        self.custom_slider.pack(side='left', padx=(0, 10), fill='x', expand=True)

        # Set Custom button
        self.custom_button = ttk.Button(
            control_frame,
            text="Set Custom",
            command=self.set_custom_temp,
            style='TButton'
        )
        self.custom_button.pack(side='left')

    def create_chamber_controls(self):
        """Create chamber control buttons"""
        self.control_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.control_frame.pack(fill='x', pady=5, padx=5)

        self.run_button = ttk.Button(
            self.control_frame,
            text="START CHAMBER",
            command=self.start_chamber,
            style='TButton',
            state='disabled'
        )
        self.run_button.pack(side='left', padx=10, pady=10, fill='x', expand=True)

        self.stop_button = ttk.Button(
            self.control_frame,
            text="STOP CHAMBER",
            command=self.stop_chamber,
            style='TButton',
            state='disabled'
        )
        self.stop_button.pack(side='left', padx=10, pady=10, fill='x', expand=True)

        # Additional controls
        self.advanced_button = ttk.Button(
            self.control_frame,
            text="ADVANCED",
            command=self.show_advanced_settings,
            style='TButton'
        )
        self.advanced_button.pack(side='left', padx=10, pady=10)

    def create_plot_area(self):
        """Create the temperature plot area"""
        self.plot_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.plot_frame.pack(fill='both', expand=True, pady=5, padx=5)

        # Initialize plot data
        self.x_data = []
        self.y_data = []

    def create_status_bar(self):
        """Create the status bar at the bottom"""
        self.status_bar = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.status_bar.pack(fill='x', pady=(5, 0), padx=5)

        self.system_status = tk.StringVar(value="System Ready")
        ttk.Label(
            self.status_bar,
            textvariable=self.system_status,
            font=('Helvetica', 9),
            style='TLabel'
        ).pack(side='left', padx=10, pady=5)

        ttk.Label(
            self.status_bar,
            text="v1.0.0",
            font=('Helvetica', 9),
            style='TLabel'
        ).pack(side='right', padx=10, pady=5)

    def setup_plot(self):
        """Configure the temperature plot"""
        plt.style.use('dark_background')
        self.fig = Figure(figsize=(8, 4), dpi=80, facecolor=self.colors['card'])
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#2E2E2E')

        # Customize plot appearance
        self.ax.grid(True, linestyle='--', alpha=0.3, color='#555555')
        self.ax.set_xlabel('Time (minutes)', color=self.colors['text'])
        self.ax.set_ylabel('Temperature (°C)', color=self.colors['text'])
        self.ax.set_title('Temperature Profile', color=self.colors['text'])
        self.ax.set_ylim(self.config['min_temp'] - 5, self.config['max_temp'] + 5)
        self.ax.tick_params(colors=self.colors['text'])

        for spine in self.ax.spines.values():
            spine.set_edgecolor('#555555')

        # Create initial empty data
        self.line, = self.ax.plot([], [], color=self.get_temp_color(25), linewidth=2)

        # Create the canvas
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill='both', expand=True, padx=10, pady=10)

    def get_temp_color(self, temp):
        """Get color for a specific temperature using HSV gradient"""
        normalized = (temp - self.config['min_temp']) / (self.config['max_temp'] - self.config['min_temp'])
        hue = 0.66 * (1 - normalized)
        saturation = 1.0
        value = 0.7 + 0.3 * normalized
        r, g, b = hsv_to_rgb(hue, saturation, value)
        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

    def create_preset_button(self, parent, text, command, color):
        """Helper to create a preset temperature button"""
        btn = ttk.Button(
            parent,
            text=text,
            command=command,
            style='TButton'
        )
        btn.pack(side='left', padx=5, pady=5, fill='x', expand=True)
        return btn

    def start_threads(self):
        """Start all background threads"""
        self.simulation_thread = Thread(target=self.temperature_simulation)
        self.simulation_thread.daemon = True
        self.simulation_thread.start()

        self.plot_update_thread = Thread(target=self.update_plot_data)
        self.plot_update_thread.daemon = True
        self.plot_update_thread.start()

    def temperature_simulation(self):
        """Simulate temperature changes"""
        while not self._shutdown_event.is_set():
            if self.is_running and self.is_connected:
                # Move toward target temperature
                diff = self.target_temp - self.current_temp
                step = diff * self.config['simulation_speed'] + random.uniform(-0.1, 0.1)
                self.current_temp += step
            else:
                # Drift toward room temperature
                self.current_temp += (25 - self.current_temp) * 0.01 + random.uniform(-0.05, 0.05)

            # Update display
            self.temp_var.set(f"{self.current_temp:.1f} °C")

            # Add to plot data
            self.command_queue.put(('add_data', (time.time(), self.current_temp)))

            time.sleep(self.config['update_interval'])

    def update_plot_data(self):
        """Update the plot with new data"""
        while not self._shutdown_event.is_set():
            try:
                # Process all pending commands
                while True:
                    cmd, data = self.command_queue.get_nowait()
                    if cmd == 'add_data':
                        timestamp, temp = data
                        elapsed_minutes = (timestamp - self.start_time) / 60
                        self.x_data.append(elapsed_minutes)
                        self.y_data.append(temp)

                        # Keep only the last N points
                        if len(self.x_data) > self.config['max_data_points']:
                            self.x_data = self.x_data[-self.config['max_data_points']:]
                            self.y_data = self.y_data[-self.config['max_data_points']:]

                        # Update plot on main thread
                        self.root.after(0, self.redraw_plot)
            except queue.Empty:
                pass

            time.sleep(0.1)

    def redraw_plot(self):
        """Redraw the plot with current data"""
        if not self.x_data:
            return

        self.line.set_data(self.x_data, self.y_data)
        self.line.set_color(self.get_temp_color(self.current_temp))

        # Adjust plot limits
        self.ax.set_xlim(0, max(self.x_data) + 0.5)
        self.ax.set_ylim(
            min(self.y_data) - 5 if len(self.y_data) > 0 else self.config['min_temp'],
            max(self.y_data) + 5 if len(self.y_data) > 0 else self.config['max_temp']
        )

        self.canvas.draw()

    def connect_chamber(self):
        """Connect to the thermal chamber"""
        ip_address = self.ip_var.get()

        try:
            # Validate IP address
            socket.inet_aton(ip_address)

            # Simulate connection (in a real app, this would actually connect)
            self.is_connected = True
            self.status_var.set(f"Connected to {ip_address}")
            self.status_label.configure(background=self.get_temp_color(25))
            self.connect_button.config(state='disabled')
            self.disconnect_button.config(state='normal')
            self.ip_combobox.config(state='disabled')
            self.run_button.config(state='normal')

            # Initialize simulation
            self.start_time = time.time()
            self.x_data = []
            self.y_data = []

            self.system_status.set(f"Connected to chamber at {ip_address}")

            # Simulate getting device information
            self.update_device_info({
                'manufacturer': 'ThermoTech',
                'model': f"MasterTemp {random.choice(['Pro', 'Elite', 'Xtreme'])}",
                'serial': f"THC-2023-{random.randint(1000, 9999)}",
                'firmware': f"v{random.randint(1, 5)}.{random.randint(0, 9)}.{random.randint(0, 9)}"
            })

            # Show the serial window
            self.show_serial_window()

        except socket.error:
            messagebox.showerror("Invalid IP", "Please enter a valid IP address")

    def disconnect_chamber(self):
        """Disconnect from the thermal chamber"""
        self.is_connected = False
        self.is_running = False
        self.status_var.set("Disconnected")
        self.status_label.configure(background=self.get_temp_color(25))
        self.connect_button.config(state='normal')
        self.disconnect_button.config(state='disabled')
        self.ip_combobox.config(state='normal')
        self.run_button.config(state='disabled')
        self.stop_button.config(state='disabled')
        self.system_status.set("Disconnected from chamber")

        # Reset device info
        self.update_device_info({
            'manufacturer': 'Not Connected',
            'model': 'Not Connected',
            'serial': 'Not Connected',
            'firmware': 'Not Connected'
        })

    def on_temp_entry(self, event=None):
        """Handle temperature entry from keyboard"""
        try:
            temp = float(self.temp_entry.get())
            if self.config['min_temp'] <= temp <= self.config['max_temp']:
                self.set_temp(temp)
                self.custom_temp.set(temp)
            else:
                self.status_var.set(
                    f"Temperature must be between {self.config['min_temp']} and {self.config['max_temp']}")
                self.status_label.configure(background=self.get_temp_color(25))
        except ValueError:
            self.status_var.set("Invalid temperature value")
            self.status_label.configure(background=self.get_temp_color(25))

    def on_slider_move(self, value):
        """Update entry field when slider moves"""
        self.temp_entry.delete(0, tk.END)
        self.temp_entry.insert(0, f"{float(value):.1f}")

    def set_temp(self, temp):
        """Set the target temperature"""
        if not self.is_connected:
            self.status_var.set("Connect to chamber first!")
            self.status_label.configure(background=self.get_temp_color(25))
            return

        self.target_temp = temp
        self.target_var.set(f"{self.target_temp:.1f} °C")
        self.custom_temp.set(self.target_temp)
        self.temp_entry.delete(0, tk.END)
        self.temp_entry.insert(0, f"{self.target_temp:.1f}")

        # Update status
        self.status_var.set(f"Target set to {self.target_temp}°C")
        self.status_label.configure(background=self.get_temp_color(self.target_temp))

    def set_custom_temp(self):
        """Set temperature from custom control"""
        self.set_temp(self.custom_temp.get())

    def start_chamber(self):
        """Start the thermal chamber"""
        if not self.is_connected:
            self.status_var.set("Connect to chamber first!")
            self.status_label.configure(background=self.get_temp_color(25))
            return

        self.is_running = True
        self.status_var.set(f"Running at {self.target_temp}°C")
        self.status_label.configure(background=self.get_temp_color(self.target_temp))
        self.run_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.system_status.set(f"Chamber running at {self.target_temp}°C")

    def stop_chamber(self):
        """Stop the thermal chamber"""
        self.is_running = False
        self.status_var.set("Connected (Idle)" if self.is_connected else "Disconnected")
        self.status_label.configure(background=self.get_temp_color(25))
        self.run_button.config(state='normal')
        self.stop_button.config(state='disabled')
        self.system_status.set("Chamber stopped")

    def show_advanced_settings(self):
        """Show advanced settings dialog"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Advanced Settings")
        dialog.geometry("400x300")
        dialog.resizable(False, False)

        ttk.Label(dialog, text="Advanced Chamber Settings", font=('Helvetica', 14)).pack(pady=10)

        # Add your advanced settings controls here
        # Example:
        ttk.Label(dialog, text="Temperature Ramp Rate:").pack(pady=5)
        ttk.Scale(dialog, from_=0.1, to=5.0, orient='horizontal').pack(fill='x', padx=20)

        ttk.Button(dialog, text="Save", command=dialog.destroy).pack(pady=20)

    def load_settings(self):
        """Load application settings"""
        # In a real app, this would load from a config file
        pass

    def save_settings(self):
        """Save application settings"""
        # In a real app, this would save to a config file
        pass

    def on_closing(self):
        """Handle application shutdown"""
        self._shutdown_event.set()
        self.save_settings()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ThermalChamberController(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()