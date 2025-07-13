import tkinter as tk
from tkinter import ttk, Frame, Label, Button, Scale, Canvas, Entry
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
from threading import Thread
import time
import random
from colorsys import hsv_to_rgb
from VotschTechnikClimateChamber.ClimateChamber import ClimateChamber
from version import __version__


class DarkThemeThermalChamber:
    def __init__(self, root):
        self.root = root
        self.root.title("Thermal Chamber Controller - Gradient Mode")
        self.root.geometry("1100x750")
        self.root.configure(bg='#121212')

        # Application settings
        self.tcam = None
        # self.default_port = 2049  # Default port for chamber communication

        # Color settings
        self.bg_color = '#121212'
        self.card_color = '#1E1E1E'
        self.text_color = '#FFFFFF'

        # Temperature range
        self.min_temp = -40
        self.max_temp = 130
        self.temp_range = self.max_temp - self.min_temp

        # Configure styles
        self.style = ttk.Style()
        self.style.theme_use('clam')

        # Custom widget styles
        self.style.configure('TFrame', background=self.bg_color)
        self.style.configure('TLabel', background=self.bg_color, foreground=self.text_color)
        self.style.configure('Header.TLabel',
                             background=self.get_temp_color(25),
                             foreground='white',
                             font=('Helvetica', 16, 'bold'),
                             padding=10)
        self.style.configure('Card.TFrame', background=self.card_color, relief='flat', borderwidth=0)
        self.style.configure('Temp.TLabel',
                             background=self.card_color,
                             foreground=self.text_color,
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
                             fieldbackground=self.card_color,
                             foreground=self.text_color,
                             insertcolor=self.text_color,
                             borderwidth=1,
                             relief='flat')

        # Create main container with Notebook (tabs)
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # Create tabs
        self.create_control_tab()
        self.create_settings_tab()
        self.create_logs_tab()

        # Initialize state
        self.current_temp = 25.0
        self.target_temp = 25.0
        self.is_running = False
        self.is_connected = False
        self.running = True

        # Start temperature simulation thread
        self.simulation_thread = Thread(target=self.simulate_temperature)
        self.simulation_thread.daemon = True
        self.simulation_thread.start()

    def create_control_tab(self):
        """Create the main control tab"""
        self.control_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.control_tab, text="Control")

        # Header
        self.header_frame = ttk.Frame(self.control_tab, style='Header.TFrame')
        self.header_frame.pack(fill='x', pady=(0, 10))

        self.header_label = ttk.Label(self.header_frame,
                                      text=f"VOTSCH-TECHNIK THERMAL CHAMBER CONTROLLER - v.{__version__}",
                                      style='Header.TLabel')
        self.header_label.pack(fill='x')

        # IP Selection with Connect/Disconnect buttons
        self.ip_frame = ttk.Frame(self.control_tab, style='Card.TFrame')
        self.ip_frame.pack(fill='x', pady=5, padx=5)

        # IP selection section
        ip_control_frame = ttk.Frame(self.ip_frame, style='Card.TFrame')
        ip_control_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(ip_control_frame, text="Chamber IP:", font=('Helvetica', 11)).pack(side='left', padx=(0, 5))

        self.ip_var = tk.StringVar(value="192.168.0.11")
        self.ip_combobox = ttk.Combobox(ip_control_frame,
                                        textvariable=self.ip_var,
                                        values=["192.168.0.11", "192.168.0.21", "192.168.0.31", "localhost"],
                                        font=('Helvetica', 10),
                                        width=15)
        self.ip_combobox.pack(side='left', padx=(0, 5))

        # Connection buttons
        self.connect_button = Button(ip_control_frame,
                                     text="Connect",
                                     command=self.connect_chamber,
                                     bg=self.get_temp_color(25),
                                     fg='white',
                                     font=('Helvetica', 10, 'bold'),
                                     relief='flat',
                                     padx=12,
                                     activebackground=self.get_temp_color(40),
                                     borderwidth=0)
        self.connect_button.pack(side='left', padx=5)

        self.disconnect_button = Button(ip_control_frame,
                                        text="Disconnect",
                                        command=self.disconnect_chamber,
                                        bg=self.get_temp_color(25),
                                        fg='white',
                                        font=('Helvetica', 10, 'bold'),
                                        relief='flat',
                                        padx=10,
                                        state='disabled',
                                        activebackground=self.get_temp_color(10),
                                        borderwidth=0)
        self.disconnect_button.pack(side='left', padx=5)

        # Chamber ID
        self.chamber_id = tk.StringVar(value="No Id                      ")
        self.chamber_id_label = ttk.Label(ip_control_frame,
                                          textvariable=self.chamber_id,
                                          style='Status.TLabel')
        self.chamber_id_label.pack(side='left', padx=(0, 5))

        # Status indicator
        self.status_var = tk.StringVar(value="Disconnected")
        self.status_label = ttk.Label(ip_control_frame,
                                      textvariable=self.status_var,
                                      style='Status.TLabel')
        self.status_label.pack(side='right', padx=(0, 5))

        # Temperature Display
        self.temp_display_frame = ttk.Frame(self.control_tab, style='Card.TFrame')
        self.temp_display_frame.pack(fill='x', pady=5, padx=5)

        # Current Temp
        current_frame = ttk.Frame(self.temp_display_frame, style='Card.TFrame')
        current_frame.pack(side='left', fill='x', expand=True, padx=10, pady=10)

        ttk.Label(current_frame, text="Current Temperature:", font=('Helvetica', 12)).pack(anchor='w')

        self.temp_var = tk.StringVar(value="25.0 °C")
        self.temp_label = ttk.Label(current_frame,
                                    textvariable=self.temp_var,
                                    style='Temp.TLabel')
        self.temp_label.pack(fill='x', pady=5)

        # Target Temp
        target_frame = ttk.Frame(self.temp_display_frame, style='Card.TFrame')
        target_frame.pack(side='right', fill='x', expand=True, padx=10, pady=10)

        ttk.Label(target_frame, text="Target Temperature:", font=('Helvetica', 12)).pack(anchor='w')

        self.target_var = tk.StringVar(value="25.0 °C")
        self.target_label = ttk.Label(target_frame,
                                      textvariable=self.target_var,
                                      style='Temp.TLabel')
        self.target_label.pack(fill='x', pady=5)

        # Preset Buttons with gradient colors
        self.preset_frame = ttk.Frame(self.control_tab, style='Card.TFrame')
        self.preset_frame.pack(fill='x', pady=5, padx=5)

        ttk.Label(self.preset_frame, text="Preset Temperatures:", font=('Helvetica', 12)).pack(anchor='w', padx=10,
                                                                                               pady=(10, 5))

        button_frame = ttk.Frame(self.preset_frame, style='Card.TFrame')
        button_frame.pack(fill='x', padx=10, pady=(0, 10))

        preset_temps = [-40, -30, -20, -10, 0, 25, 40, 50, 85, 100, 120]
        for temp in preset_temps:
            self.create_preset_button(button_frame, f"{temp}°C",
                                      lambda t=temp: self.set_temp(t),
                                      self.get_temp_color(temp))

        # Custom Temperature Control
        self.custom_frame = ttk.Frame(self.control_tab, style='Card.TFrame')
        self.custom_frame.pack(fill='x', pady=5, padx=5)

        ttk.Label(self.custom_frame, text="Custom Temperature:", font=('Helvetica', 12)).pack(anchor='w', padx=10,
                                                                                              pady=(10, 5))

        control_frame = ttk.Frame(self.custom_frame, style='Card.TFrame')
        control_frame.pack(fill='x', padx=10, pady=(0, 10))

        # Temperature slider
        self.custom_temp = tk.DoubleVar(value=25.0)
        self.custom_slider = Scale(control_frame,
                                   from_=self.min_temp,
                                   to=self.max_temp,
                                   orient="horizontal",
                                   variable=self.custom_temp,
                                   bg=self.card_color,
                                   fg=self.text_color,
                                   highlightthickness=0,
                                   troughcolor='#333333',
                                   length=400,
                                   command=self.on_slider_move)
        self.custom_slider.pack(side='left', padx=(0, 10), fill='x', expand=True)

        self.temp_entry = ttk.Entry(control_frame,
                                    font=('Helvetica', 18),
                                    width=6,
                                    style='TEntry')
        self.temp_entry.insert(0, "25.0")
        self.temp_entry.pack(side='left', padx=(0, 10))
        self.temp_entry.bind('<Return>', self.on_temp_entry)

        # Set Custom button
        self.custom_button = Button(control_frame,
                                    text="Set Custom",
                                    command=self.set_custom_temp,
                                    bg=self.get_temp_color(25),
                                    fg='white',
                                    font=('Helvetica', 14, 'bold'),
                                    relief='flat',
                                    activebackground=self.get_temp_color(40),
                                    borderwidth=1)
        self.custom_button.pack(side='left')

        # Control Buttons
        self.control_frame = ttk.Frame(self.control_tab, style='Card.TFrame')
        self.control_frame.pack(fill='x', pady=5, padx=5)

        self.run_button = Button(self.control_frame,
                                 text="START CHAMBER",
                                 command=self.start_chamber,
                                 bg=self.get_temp_color(25),
                                 fg='white',
                                 font=('Helvetica', 12, 'bold'),
                                 relief='flat',
                                 padx=20,
                                 pady=8,
                                 activebackground=self.get_temp_color(40),
                                 borderwidth=0,
                                 state='disabled')
        self.run_button.pack(side='left', padx=10, pady=10, fill='x', expand=True)

        self.stop_button = Button(self.control_frame,
                                  text="STOP CHAMBER",
                                  command=self.stop_chamber,
                                  bg="red",
                                  fg='white',
                                  font=('Helvetica', 12, 'bold'),
                                  relief='flat',
                                  padx=20,
                                  pady=8,
                                  state='disabled',
                                  activebackground=self.get_temp_color(10),
                                  borderwidth=0)
        self.stop_button.pack(side='left', padx=10, pady=10, fill='x', expand=True)

        # Plot Area
        self.plot_frame = ttk.Frame(self.control_tab, style='Card.TFrame')
        self.plot_frame.pack(fill='both', expand=True, pady=5, padx=5)

        self.setup_plot()

    def create_settings_tab(self):
        """Create the settings tab with IP configuration"""
        self.settings_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.settings_tab, text="Settings")

        # Main settings frame
        settings_frame = ttk.Frame(self.settings_tab, style='Card.TFrame')
        settings_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Network Settings Section
        network_frame = ttk.LabelFrame(settings_frame, text="Network Settings", style='Card.TFrame')
        network_frame.pack(fill='x', padx=10, pady=10)

        # IP Address Configuration
        ttk.Label(network_frame, text="Chamber IP Address:").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        self.ip_settings_entry = ttk.Entry(network_frame, width=20)
        self.ip_settings_entry.insert(0, self.ip_var.get())
        self.ip_settings_entry.grid(row=0, column=1, padx=5, pady=5, sticky='w')

        # Port Configuration
        # ttk.Label(network_frame, text="Port Number:").grid(row=1, column=0, sticky='w', padx=5, pady=5)
        # self.port_entry = ttk.Entry(network_frame, width=8)
        # self.port_entry.insert(0, str(self.default_port))
        # self.port_entry.grid(row=1, column=1, padx=5, pady=5, sticky='w')

        # Chamber Settings Section
        chamber_frame = ttk.LabelFrame(settings_frame, text="Chamber Settings", style='Card.TFrame')
        chamber_frame.pack(fill='x', padx=10, pady=10)

        # Temperature limits
        ttk.Label(chamber_frame, text="Temperature Limits:").grid(row=0, column=0, sticky='w', padx=5, pady=5)
        self.min_temp_entry = ttk.Entry(chamber_frame, width=8)
        self.min_temp_entry.insert(0, str(self.min_temp))
        self.min_temp_entry.grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(chamber_frame, text="to").grid(row=0, column=2, padx=5)
        self.max_temp_entry = ttk.Entry(chamber_frame, width=8)
        self.max_temp_entry.insert(0, str(self.max_temp))
        self.max_temp_entry.grid(row=0, column=3, padx=5, pady=5)

        # Ramp rate
        ttk.Label(chamber_frame, text="Ramp Rate (°C/min):").grid(row=1, column=0, sticky='w', padx=5, pady=5)
        self.ramp_rate = ttk.Entry(chamber_frame, width=8)
        self.ramp_rate.insert(0, "5.0")
        self.ramp_rate.grid(row=1, column=1, padx=5, pady=5)

        # Save settings button
        save_btn = Button(settings_frame,
                          text="Save All Settings",
                          command=self.save_settings,
                          bg=self.get_temp_color(25),
                          fg='white',
                          font=('Helvetica', 10, 'bold'),
                          relief='flat',
                          padx=10,
                          pady=5,
                          activebackground=self.get_temp_color(40),
                          borderwidth=0)
        save_btn.pack(pady=10)

    def create_logs_tab(self):
        """Create the logs tab"""
        self.logs_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.logs_tab, text="Logs")

        # Logs frame
        logs_frame = ttk.Frame(self.logs_tab, style='Card.TFrame')
        logs_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Log text widget
        self.log_text = tk.Text(logs_frame,
                                bg=self.card_color,
                                fg=self.text_color,
                                insertbackground=self.text_color,
                                font=('Courier', 10),
                                wrap=tk.WORD)
        self.log_text.pack(fill='both', expand=True, padx=5, pady=5)

        # Scrollbar
        scrollbar = ttk.Scrollbar(logs_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

        # Add initial log message
        self.log_text.insert(tk.END, "System initialized\n")
        self.log_text.insert(tk.END, "Waiting for connection...\n")

    def save_settings(self):
        """Save all settings from the settings tab"""
        try:
            # Save network settings
            new_ip = self.ip_settings_entry.get()
            if new_ip:  # Basic validation
                self.ip_var.set(new_ip)
                # Add to combobox if not already there
                if new_ip not in self.ip_combobox['values']:
                    current_values = list(self.ip_combobox['values'])
                    current_values.append(new_ip)
                    self.ip_combobox['values'] = current_values
                self.ip_combobox.set(new_ip)
                self.log_text.insert(tk.END, f"IP address updated to {new_ip}\n")

            # Save port setting
            # new_port = int(self.port_entry.get())
            # if 1 <= new_port <= 65535:
            #     self.default_port = new_port
            #     self.log_text.insert(tk.END, f"Port updated to {new_port}\n")
            # else:
            #     raise ValueError("Port must be between 1 and 65535")

            # Save temperature limits
            new_min = float(self.min_temp_entry.get())
            new_max = float(self.max_temp_entry.get())
            if new_min >= new_max:
                raise ValueError("Min temperature must be less than max")

            self.min_temp = new_min
            self.max_temp = new_max
            self.temp_range = self.max_temp - self.min_temp

            # Update plot limits
            self.ax.set_ylim(self.min_temp - 5, self.max_temp + 5)
            self.canvas.draw()

            self.log_text.insert(tk.END, f"Temperature range updated: {self.min_temp} to {self.max_temp}°C\n")

            # Save ramp rate
            new_ramp_rate = float(self.ramp_rate.get())
            if new_ramp_rate <= 0:
                raise ValueError("Ramp rate must be positive")
            # Here you would implement ramp rate functionality if needed

            self.log_text.insert(tk.END, "All settings saved successfully\n")
            self.log_text.see(tk.END)

        except ValueError as e:
            self.log_text.insert(tk.END, f"Error saving settings: {str(e)}\n")
            self.log_text.see(tk.END)

    def get_temp_color(self, temp):
        """Get color for a specific temperature using HSV gradient"""
        normalized = (temp - self.min_temp) / self.temp_range
        hue = 0.66 * (1 - normalized)
        saturation = 1.0
        value = 0.7 + 0.3 * normalized
        r, g, b = hsv_to_rgb(hue, saturation, value)
        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

    def create_preset_button(self, parent, text, command, color):
        btn = Button(parent,
                     text=text,
                     command=command,
                     bg=color,
                     fg='white',
                     font=('Helvetica', 10, 'bold'),
                     relief='flat',
                     padx=12,
                     pady=6,
                     activebackground=self.adjust_brightness(color, 1.2),
                     borderwidth=0)
        btn.pack(side='left', padx=5, pady=5, fill='x', expand=True)
        return btn

    def adjust_brightness(self, color_hex, factor):
        """Adjust color brightness by a factor"""
        r = int(color_hex[1:3], 16)
        g = int(color_hex[3:5], 16)
        b = int(color_hex[5:7], 16)
        r = min(255, int(r * factor))
        g = min(255, int(g * factor))
        b = min(255, int(b * factor))
        return f"#{r:02x}{g:02x}{b:02x}"

    def connect_chamber(self):
        """Connect to the thermal chamber"""
        try:
            self.is_connected = True
            ip_address = self.ip_var.get()
            self.status_var.set(f"Connected to {ip_address}")
            self.status_label.configure(background=self.get_temp_color(25))
            self.connect_button.config(state='disabled')
            self.disconnect_button.config(state='normal')
            self.ip_combobox.config(state='disabled')
            self.run_button.config(state='normal')

            # Connect to chamber (simulated here)
            self.tcam = ClimateChamber(ip_address, self.min_temp, self.max_temp)
            self.chamber_id.set(f"ID:{self.tcam.idn}")

            self.log_text.insert(tk.END, f"Connected to chamber ID:{self.tcam.idn} at {ip_address}\n")
            self.log_text.see(tk.END)
        except Exception as e:
            self.is_connected = False
            self.status_var.set("Connection failed")
            self.log_text.insert(tk.END, f"Connection error: {str(e)}\n")
            self.log_text.see(tk.END)

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
        self.tcam.disconnect()
        self.tcam = None
        self.chamber_id.set("NO ID")
        self.log_text.insert(tk.END, "Disconnected from chamber\n")
        self.log_text.see(tk.END)

    def on_temp_entry(self, event=None):
        """Handle temperature entry from keyboard"""
        try:
            temp = float(self.temp_entry.get())
            if self.min_temp <= temp <= self.max_temp:
                self.set_temp(temp)
                self.custom_temp.set(temp)
                self.log_text.insert(tk.END, f"Temperature set to {temp}°C\n")
                self.log_text.see(tk.END)
            else:
                self.status_var.set(f"Temperature must be between {self.min_temp} and {self.max_temp}")
                self.status_label.configure(background=self.get_temp_color(25))
                self.log_text.insert(tk.END, f"Invalid temperature: {temp}°C (out of range)\n")
                self.log_text.see(tk.END)
        except ValueError:
            self.status_var.set("Invalid temperature value")
            self.status_label.configure(background=self.get_temp_color(25))
            self.log_text.insert(tk.END, "Invalid temperature value entered\n")
            self.log_text.see(tk.END)

    def on_slider_move(self, value):
        """Update entry field when slider moves"""
        self.temp_entry.delete(0, tk.END)
        self.temp_entry.insert(0, f"{float(value):.1f}")

    def setup_plot(self):
        """Configure the temperature plot"""
        plt.style.use('dark_background')
        self.fig = Figure(figsize=(8, 4), dpi=80, facecolor=self.card_color)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#2E2E2E')

        # Customize plot appearance
        self.ax.grid(True, linestyle='--', alpha=0.3, color='#555555')
        self.ax.set_xlabel('Time (minutes)', color=self.text_color)
        self.ax.set_ylabel('Temperature (°C)', color=self.text_color)
        self.ax.set_title('Temperature Profile', color=self.text_color)
        self.ax.set_ylim(self.min_temp - 5, self.max_temp + 5)
        self.ax.tick_params(colors=self.text_color)

        for spine in self.ax.spines.values():
            spine.set_edgecolor('#555555')

        # Create initial empty data
        self.x_data = []
        self.y_data = []
        self.line, = self.ax.plot([], [], color=self.get_temp_color(25), linewidth=2)

        # Create the canvas
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill='both', expand=True, padx=10, pady=10)

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

        # Update button colors
        self.custom_button.config(bg=self.get_temp_color(temp),
                                  activebackground=self.adjust_brightness(self.get_temp_color(temp), 1.2))


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
        self.tcam.temperature_set_point = self.target_temp
        self.log_text.insert(tk.END, f"Chamber started at {self.target_temp}°C\n")
        self.log_text.see(tk.END)


    def stop_chamber(self):
        """Stop the thermal chamber"""
        self.is_running = False
        self.status_var.set("Connected (Idle)" if self.is_connected else "Disconnected")
        self.status_label.configure(background=self.get_temp_color(25))
        self.run_button.config(state='normal')
        self.stop_button.config(state='disabled')
        self.tcam.stop()
        self.log_text.insert(tk.END, "Chamber stopped\n")
        self.log_text.see(tk.END)

    def simulate_temperature(self):
        """Simulate temperature changes"""
        start_time = time.time()
        while self.running:
            # Add new data point every second
            elapsed_minutes = (time.time() - start_time) / 60
            self.x_data.append(elapsed_minutes)

            # Simulate temperature change toward target
            if self.is_running and self.is_connected:
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

            # Update display
            self.temp_var.set(f"{self.current_temp:.1f} °C")

            # Update the plot on the main thread
            self.root.after(0, self.update_plot)

            time.sleep(0.5)

    def update_plot(self):
        """Update the temperature plot"""
        self.line.set_data(self.x_data, self.y_data)
        self.line.set_color(self.get_temp_color(self.current_temp))

        # Adjust plot limits
        if len(self.x_data) > 0:
            self.ax.set_xlim(0, max(self.x_data) + 0.5)

        # Redraw the plot
        self.canvas.draw()

    def on_closing(self):
        """Handle application shutdown"""
        self.running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = DarkThemeThermalChamber(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()