import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import random

class ThermalChamberGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Thermal Chamber Controller")
        self.root.geometry("800x600")
        self.root.configure(bg="#f2f2f2")

        self.current_temperature = 25.0
        self.temperature_history = [self.current_temperature]
        self.time = [0]
        self.running = False

        self.build_ui()
        self.update_plot()

    def build_ui(self):
        # === IP Selector ===
        ip_frame = ttk.LabelFrame(self.root, text="Chamber IP", padding=10)
        ip_frame.pack(pady=10, padx=10, fill="x")

        self.ip_var = tk.StringVar()
        ip_menu = ttk.Combobox(ip_frame, textvariable=self.ip_var, values=[
            "192.168.0.100", "192.168.0.101", "192.168.0.102"
        ])
        ip_menu.current(0)
        ip_menu.pack(padx=10, fill="x")

        # === Controls ===
        control_frame = ttk.LabelFrame(self.root, text="Temperature Controls", padding=10)
        control_frame.pack(pady=10, padx=10, fill="x")

        for temp in [-40, 25, 60, 85]:
            btn = ttk.Button(control_frame, text=f"{temp}°C", command=lambda t=temp: self.set_temperature(t))
            btn.pack(side="left", padx=10, pady=5, expand=True)

        self.custom_temp_var = tk.DoubleVar()
        custom_entry = ttk.Entry(control_frame, textvariable=self.custom_temp_var)
        custom_entry.pack(side="left", padx=10)

        custom_btn = ttk.Button(control_frame, text="Set Custom", command=self.set_custom_temperature)
        custom_btn.pack(side="left", padx=10)

        # === Start/Stop Buttons ===
        action_frame = ttk.Frame(self.root)
        action_frame.pack(pady=10)

        self.start_btn = ttk.Button(action_frame, text="Start Chamber", command=self.start_chamber)
        self.start_btn.pack(side="left", padx=20)

        self.stop_btn = ttk.Button(action_frame, text="Stop Chamber", command=self.stop_chamber)
        self.stop_btn.pack(side="left", padx=20)

        # === Current Temp Display ===
        self.temp_display = ttk.Label(self.root, text="Current Temp: 25.0°C", font=("Arial", 20))
        self.temp_display.pack(pady=10)

        # === Plot ===
        plot_frame = ttk.Frame(self.root)
        plot_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.fig, self.ax = plt.subplots(figsize=(7, 3))
        self.line, = self.ax.plot(self.time, self.temperature_history, label="Temperature")
        self.ax.set_title("Temperature Over Time")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Temperature (°C)")
        self.ax.grid(True)

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def update_plot(self):
        if self.running:
            self.current_temperature += random.uniform(-0.2, 0.2)
            self.temperature_history.append(self.current_temperature)
            self.time.append(self.time[-1] + 1)
            self.temp_display.config(text=f"Current Temp: {self.current_temperature:.1f}°C")

            if len(self.time) > 100:
                self.time = self.time[-100:]
                self.temperature_history = self.temperature_history[-100:]

            self.line.set_data(self.time, self.temperature_history)
            self.ax.set_xlim(self.time[0], self.time[-1])
            self.ax.set_ylim(min(self.temperature_history) - 5, max(self.temperature_history) + 5)
            self.canvas.draw()

        self.root.after(1000, self.update_plot)

    def set_temperature(self, temp):
        self.current_temperature = temp
        self.temp_display.config(text=f"Current Temp: {self.current_temperature:.1f}°C")

    def set_custom_temperature(self):
        try:
            temp = self.custom_temp_var.get()
            self.set_temperature(temp)
        except tk.TclError:
            messagebox.showerror("Invalid input", "Please enter a valid number.")

    def start_chamber(self):
        self.running = True

    def stop_chamber(self):
        self.running = False


if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TLabel", font=("Arial", 12), background="#f2f2f2")
    style.configure("TButton", font=("Arial", 12), padding=6)
    style.configure("TEntry", font=("Arial", 12))
    style.configure("TCombobox", font=("Arial", 12))

    app = ThermalChamberGUI(root)
    root.mainloop()
