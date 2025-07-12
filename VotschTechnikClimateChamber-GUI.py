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


class DarkThemeThermalChamber:
    def __init__(self, root):
        self.root = root
        self.root.title("Thermal Chamber Controller - Gradient Mode")
        self.root.geometry("1100x750")
        self.root.configure(bg='#121212')

        # Color settings
        self.bg_color = '#121212'
        self.card_color = '#1E1E1E'
        self.text_color = '#FFFFFF'

        # Temperature range
        self.min_temp = -40
        self.max_temp = 150
        self.temp_range = self.max_temp - self.min_temp

        # Configure styles
        self.style = ttk.Style()
        self.style.theme_use('clam')

        # Custom widget styles
        self.style.configure('TFrame', background=self.bg_color)
        self.style.configure('TLabel', background=self.bg_color, foreground=self.text_color)
        self.style.configure('Header.TLabel',
                             background=self.get_temp_color(25),  # Neutral color at 25°C
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

        # Create main container
        self.main_frame = ttk.Frame(root, style='TFrame')
        self.main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Header
        self.header_frame = ttk.Frame(self.main_frame, style='Header.TFrame')
        self.header_frame.pack(fill='x', pady=(0, 10))

        self.header_label = ttk.Label(self.header_frame,
                                      text="VOTSCH-TECHNIK THERMAL CHAMBER CONTROLLER",
                                      style='Header.TLabel')
        self.header_label.pack(fill='x')

        # IP Selection with Connect/Disconnect buttons
        self.ip_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.ip_frame.pack(fill='x', pady=5, padx=5)

        # IP selection section
        ip_control_frame = ttk.Frame(self.ip_frame, style='Card.TFrame')
        ip_control_frame.pack(fill='x', padx=10, pady=10)

        ttk.Label(ip_control_frame, text="Chamber IP:", font=('Helvetica', 11)).pack(side='left', padx=(0, 5))

        self.ip_var = tk.StringVar(value="192.168.1.100")
        self.ip_combobox = ttk.Combobox(ip_control_frame,
                                        textvariable=self.ip_var,
                                        values=["192.168.1.100", "192.168.1.101", "192.168.1.102", "10.0.0.50"],
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
        self.temp_display_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
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
        self.preset_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.preset_frame.pack(fill='x', pady=5, padx=5)

        ttk.Label(self.preset_frame, text="Preset Temperatures:", font=('Helvetica', 12)).pack(anchor='w', padx=10,
                                                                                               pady=(10, 5))

        button_frame = ttk.Frame(self.preset_frame, style='Card.TFrame')
        button_frame.pack(fill='x', padx=10, pady=(0, 10))

        preset_temps = [-40, -30, -20, -10, 0, 25, 40 ,50, 85, 100, 120]
        for temp in preset_temps:
            self.create_preset_button(button_frame, f"{temp}°C",
                                      lambda t=temp: self.set_temp(t),
                                      self.get_temp_color(temp))

        # Custom Temperature Control
        self.custom_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.custom_frame.pack(fill='x', pady=5, padx=5)

        ttk.Label(self.custom_frame, text="Custom Temperature:", font=('Helvetica', 12)).pack(anchor='w', padx=10,
                                                                                              pady=(10, 5))

        control_frame = ttk.Frame(self.custom_frame, style='Card.TFrame')
        control_frame.pack(fill='x', padx=10, pady=(0, 10))

        # Temperature entry field


        # Set button for keyboard entry
        # self.entry_button = Button(control_frame,
        #                            text="Set",
        #                            command=self.on_temp_entry,
        #                            bg=self.get_temp_color(25),
        #                            fg='white',
        #                            font=('Helvetica', 10, 'bold'),
        #                            relief='flat',
        #                            padx=12,
        #                            activebackground=self.get_temp_color(40),
        #                            borderwidth=0)
        # self.entry_button.pack(side='left', padx=(0, 10))

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
                                   # activebackground=self.accent_color,
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
        self.control_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
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
        self.plot_frame = ttk.Frame(self.main_frame, style='Card.TFrame')
        self.plot_frame.pack(fill='both', expand=True, pady=5, padx=5)

        self.setup_plot()

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

    def get_temp_color(self, temp):
        """Get color for a specific temperature using HSV gradient"""
        # Normalize temperature to 0-1 range
        normalized = (temp - self.min_temp) / self.temp_range

        # Create gradient from blue (cold) to red (hot) through purple
        # Hue: 0.66 (blue) -> 0.0 (red)
        hue = 0.66 * (1 - normalized)

        # Saturation: Full
        saturation = 1.0

        # Value: Slightly darker for very cold temps
        value = 0.7 + 0.3 * normalized

        # Convert HSV to RGB
        r, g, b = hsv_to_rgb(hue, saturation, value)

        # Convert to hex
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
        """Simulate connecting to the thermal chamber"""
        self.is_connected = True
        self.status_var.set(f"Connected to {self.ip_var.get()}")
        self.status_label.configure(background=self.get_temp_color(25))
        self.connect_button.config(state='disabled')
        self.disconnect_button.config(state='normal')
        self.ip_combobox.config(state='disabled')
        self.run_button.config(state='normal')
        #
        self.chamber_id.set("ID:11.22.33.44.55.66")

    def disconnect_chamber(self):
        """Simulate disconnecting from the thermal chamber"""
        self.is_connected = False
        self.is_running = False
        self.status_var.set("Disconnected")
        self.status_label.configure(background=self.get_temp_color(25))
        self.connect_button.config(state='normal')
        self.disconnect_button.config(state='disabled')
        self.ip_combobox.config(state='normal')
        self.run_button.config(state='disabled')
        self.stop_button.config(state='disabled')
        self.chamber_id.set("NO ID")

    def on_temp_entry(self, event=None):
        """Handle temperature entry from keyboard"""
        try:
            temp = float(self.temp_entry.get())
            if self.min_temp <= temp <= self.max_temp:
                self.set_temp(temp)
                self.custom_temp.set(temp)
            else:
                self.status_var.set(f"Temperature must be between {self.min_temp} and {self.max_temp}")
                self.status_label.configure(background=self.get_temp_color(25))
        except ValueError:
            self.status_var.set("Invalid temperature value")
            self.status_label.configure(background=self.get_temp_color(25))

    def on_slider_move(self, value):
        """Update entry field when slider moves"""
        self.temp_entry.delete(0, tk.END)
        self.temp_entry.insert(0, f"{float(value):.1f}")

    def setup_plot(self):
        # Create figure with dark theme
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
        self.entry_button.config(bg=self.get_temp_color(temp),
                                 activebackground=self.adjust_brightness(self.get_temp_color(temp), 1.2))

    def set_custom_temp(self):
        self.set_temp(self.custom_temp.get())

    def start_chamber(self):
        if not self.is_connected:
            self.status_var.set("Connect to chamber first!")
            self.status_label.configure(background=self.get_temp_color(25))
            return

        self.is_running = True
        self.status_var.set(f"Running at {self.target_temp}°C")
        self.status_label.configure(background=self.get_temp_color(self.target_temp))
        self.run_button.config(state='disabled')
        self.stop_button.config(state='normal')

    def stop_chamber(self):
        self.is_running = False
        self.status_var.set("Connected (Idle)" if self.is_connected else "Disconnected")
        self.status_label.configure(background=self.get_temp_color(25))
        self.run_button.config(state='normal')
        self.stop_button.config(state='disabled')

    def simulate_temperature(self):
        # Temperature simulation thread
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
        # Update plot data
        self.line.set_data(self.x_data, self.y_data)
        self.line.set_color(self.get_temp_color(self.current_temp))

        # Adjust plot limits
        if len(self.x_data) > 0:
            self.ax.set_xlim(0, max(self.x_data) + 0.5)

        # Redraw the plot
        self.canvas.draw()

    def on_closing(self):
        self.running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = DarkThemeThermalChamber(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()