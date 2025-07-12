import tkinter as tk
from tkinter import ttk, Frame, Label, Button, Scale, Canvas
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
from threading import Thread, Event
import time
import random


class ThermalChamberController:
    def __init__(self, root):
        self.root = root
        self.root.title("Thermal Chamber Controller")
        self.root.geometry("800x600")
        self.root.resizable(True, True)
        self.root.configure(bg='#f0f0f0')

        # Current temperature and state
        self.current_temp = 25.0
        self.target_temp = 25.0
        self.is_running = False
        self.chamber_ip = "192.168.1.100"

        # Create a modern style
        self.style = ttk.Style()
        self.style.configure("TButton", padding=6, font=('Helvetica', 12))
        self.style.configure("TFrame", background="#f0f0f0")
        self.style.configure("Header.TLabel", background="#2c3e50", foreground="white", font=('Helvetica', 14, 'bold'))
        self.style.configure("TempDisplay.TLabel", background="#3498db", foreground="white",
                             font=('Helvetica', 24, 'bold'))
        self.style.configure("Status.TLabel", background="#2ecc71", foreground="white", font=('Helvetica', 12))

        # Create main frames
        self.header_frame = ttk.Frame(root, style="TFrame")
        self.header_frame.pack(fill="x", padx=10, pady=10)

        self.control_frame = ttk.Frame(root, style="TFrame")
        self.control_frame.pack(fill="x", padx=10, pady=5)

        self.temp_frame = ttk.Frame(root, style="TFrame")
        self.temp_frame.pack(fill="x", padx=10, pady=5)

        self.plot_frame = ttk.Frame(root, style="TFrame")
        self.plot_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Create header
        self.header_label = ttk.Label(self.header_frame, text="THERMAL CHAMBER CONTROLLER", style="Header.TLabel")
        self.header_label.pack(fill="x", ipady=10)

        # Create IP selection
        ip_frame = ttk.Frame(self.header_frame, style="TFrame")
        ip_frame.pack(fill="x", pady=5)

        ttk.Label(ip_frame, text="Chamber IP:", font=('Helvetica', 10)).pack(side="left", padx=(0, 5))

        self.ip_var = tk.StringVar(value=self.chamber_ip)
        self.ip_combobox = ttk.Combobox(ip_frame, textvariable=self.ip_var, width=15, font=('Helvetica', 10))
        self.ip_combobox['values'] = ("192.168.1.100", "192.168.1.101", "192.168.1.102", "10.0.0.50")
        self.ip_combobox.pack(side="left", padx=(0, 10))
        self.ip_combobox.bind("<<ComboboxSelected>>", self.update_ip)

        # Create status indicator
        self.status_var = tk.StringVar(value="Chamber Stopped")
        self.status_label = ttk.Label(ip_frame, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.pack(side="right", padx=10, ipadx=10, ipady=2)

        # Create temperature display
        temp_display_frame = ttk.Frame(self.temp_frame, style="TFrame")
        temp_display_frame.pack(fill="x", pady=10)

        ttk.Label(temp_display_frame, text="Current Temperature:", font=('Helvetica', 12)).pack(side="left",
                                                                                                padx=(0, 10))

        self.temp_var = tk.StringVar(value=f"{self.current_temp:.1f} °C")
        self.temp_label = ttk.Label(temp_display_frame, textvariable=self.temp_var,
                                    style="TempDisplay.TLabel", width=10)
        self.temp_label.pack(side="left", padx=(0, 10))

        ttk.Label(temp_display_frame, text="Target Temperature:", font=('Helvetica', 12)).pack(side="left",
                                                                                               padx=(20, 10))

        self.target_var = tk.StringVar(value=f"{self.target_temp:.1f} °C")
        self.target_label = ttk.Label(temp_display_frame, textvariable=self.target_var,
                                      style="TempDisplay.TLabel", width=10)
        self.target_label.pack(side="left")

        # Create preset buttons
        preset_frame = ttk.Frame(self.control_frame, style="TFrame")
        preset_frame.pack(fill="x", pady=5)

        ttk.Label(preset_frame, text="Preset Temperatures:", font=('Helvetica', 11)).pack(side="left", padx=(0, 10))

        self.create_button(preset_frame, "-40°C", lambda: self.set_temp(-40), "#3498db")
        self.create_button(preset_frame, "+25°C", lambda: self.set_temp(25), "#2ecc71")
        self.create_button(preset_frame, "+60°C", lambda: self.set_temp(60), "#f39c12")
        self.create_button(preset_frame, "+85°C", lambda: self.set_temp(85), "#e74c3c")

        # Create custom temperature control
        custom_frame = ttk.Frame(self.control_frame, style="TFrame")
        custom_frame.pack(fill="x", pady=10)

        ttk.Label(custom_frame, text="Custom Temperature:", font=('Helvetica', 11)).pack(side="left", padx=(0, 10))

        self.custom_temp = tk.DoubleVar(value=25.0)
        self.custom_slider = Scale(custom_frame, from_=-40, to=150, orient="horizontal",
                                   variable=self.custom_temp, length=300,
                                   showvalue=True, font=('Helvetica', 10))
        self.custom_slider.pack(side="left", padx=(0, 10))

        self.custom_button = Button(custom_frame, text="Set Custom", command=self.set_custom_temp,
                                    bg="#9b59b6", fg="white", font=('Helvetica', 10, 'bold'),
                                    relief="flat", padx=10)
        self.custom_button.pack(side="left")

        # Create control buttons
        button_frame = ttk.Frame(self.control_frame, style="TFrame")
        button_frame.pack(fill="x", pady=10)

        self.run_button = Button(button_frame, text="START CHAMBER", command=self.start_chamber,
                                 bg="#2ecc71", fg="white", font=('Helvetica', 12, 'bold'),
                                 relief="flat", padx=20, pady=8)
        self.run_button.pack(side="left", padx=(0, 10))

        self.stop_button = Button(button_frame, text="STOP CHAMBER", command=self.stop_chamber,
                                  bg="#e74c3c", fg="white", font=('Helvetica', 12, 'bold'),
                                  relief="flat", padx=20, pady=8, state="disabled")
        self.stop_button.pack(side="left")

        # Create temperature plot
        self.setup_plot()

        # Start temperature simulation thread
        self.running = True
        self.simulation_thread = Thread(target=self.simulate_temperature)
        self.simulation_thread.daemon = True
        self.simulation_thread.start()

    def create_button(self, parent, text, command, color):
        btn = Button(parent, text=text, command=command,
                     bg=color, fg="white", font=('Helvetica', 10, 'bold'),
                     relief="flat", padx=12, pady=6)
        btn.pack(side="left", padx=5)
        return btn

    def setup_plot(self):
        # Create figure for plotting
        self.fig = plt.figure(figsize=(8, 4), dpi=80, facecolor='#f8f9fa')
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('#f8f9fa')

        # Customize plot appearance
        self.ax.grid(True, linestyle='--', alpha=0.7)
        self.ax.set_xlabel('Time (minutes)', fontsize=10)
        self.ax.set_ylabel('Temperature (°C)', fontsize=10)
        self.ax.set_title('Temperature Profile', fontsize=12)
        self.ax.set_ylim(-50, 100)

        # Create initial empty data
        self.x_data = []
        self.y_data = []
        self.line, = self.ax.plot([], [], 'b-', linewidth=2)

        # Create the canvas
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def update_plot(self):
        # Update plot data
        self.line.set_data(self.x_data, self.y_data)

        # Adjust plot limits
        if len(self.x_data) > 0:
            self.ax.set_xlim(0, max(self.x_data) + 0.5)

        # Redraw the plot
        self.canvas.draw()

    def set_temp(self, temp):
        self.target_temp = temp
        self.target_var.set(f"{self.target_temp:.1f} °C")
        self.custom_temp.set(self.target_temp)

    def set_custom_temp(self):
        self.set_temp(self.custom_temp.get())

    def update_ip(self, event=None):
        self.chamber_ip = self.ip_var.get()
        print(f"Chamber IP updated to: {self.chamber_ip}")

    def start_chamber(self):
        self.is_running = True
        self.status_var.set("Chamber Running")
        self.status_label.configure(style="Status.TLabel")
        self.run_button.config(state="disabled")
        self.stop_button.config(state="normal")

    def stop_chamber(self):
        self.is_running = False
        self.status_var.set("Chamber Stopped")
        self.status_label.configure(style="Status.TLabel")
        self.run_button.config(state="normal")
        self.stop_button.config(state="disabled")

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

            # Update display
            self.temp_var.set(f"{self.current_temp:.1f} °C")

            # Update the plot on the main thread
            self.root.after(0, self.update_plot)

            time.sleep(0.5)

    def on_closing(self):
        self.running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ThermalChamberController(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()