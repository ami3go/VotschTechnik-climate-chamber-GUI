import tkinter as tk
from tkinter import ttk, messagebox
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from VotschTechnikClimateChamber.ClimateChamber import ClimateChamber

class ThermalChamberGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Thermal Chamber Controller")
        self.root.geometry("1024x768")
        self.root.configure(bg="#f2f2f2")

        self.chamber = None
        self.current_temperature = 0.0
        self.temperature_history = []
        self.time = []
        self.running = False

        self.build_ui()
        self.update_plot()



    def build_ui(self):
        # === IP Selector with Connect Button in One Line ===
        ip_frame = ttk.LabelFrame(self.root, text="Chamber IP", padding=10)
        ip_frame.pack(pady=10, padx=10, fill="x")

        ip_line = ttk.Frame(ip_frame)
        ip_line.pack(fill="x")

        self.ip_var = tk.StringVar()
        ip_dropdown = ttk.Combobox(ip_line, textvariable=self.ip_var, values=[
            "192.168.0.11", "192.168.0.21", "192.168.0.31"
        ], state="readonly", width=30)
        ip_dropdown.current(0)
        ip_dropdown.pack(side="left", padx=(0, 10), expand=True, fill="x")

        connect_btn = ttk.Button(ip_line, text="Connect", command=self.connect_chamber)
        connect_btn.pack(side="left", padx=(0, 5))

        self.disconnect_btn = ttk.Button(ip_line, text="Disconnect", command=self.disconnect_chamber, state="disabled")
        self.disconnect_btn.pack(side="left")

        close_btn = ttk.Button(ip_line, text="Close Application", command=self.root.quit)
        close_btn.pack(side="left", padx=10)

        # Temperature presets + custom
        control_frame = ttk.LabelFrame(self.root, text="Temperature Controls", padding=10)
        control_frame.pack(pady=5, padx=5, fill="x")

        ## style section

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TButton", font=("Arial", 12), padding=6)

        # Green style for "Run Chamber"
        style.configure("Run.TButton", background="#4CAF50", foreground="white")
        style.map("Run.TButton", background=[("active", "#45A049")])

        # Blue for -40°C
        style.configure("Blue.TButton", background="#2196F3", foreground="white")
        style.map("Blue.TButton", background=[("active", "#1976D2")])

        # Red for +85°C
        style.configure("Red.TButton", background="#F44336", foreground="white")
        style.map("Red.TButton", background=[("active", "#D32F2F")])


        for t in (-40,-30,-20, 25, 60, 85):
            hex_color = temperature_to_hex_color(t)

            style_name = f"{t}C.TButton"
            style.configure(style_name, background=hex_color, foreground="white")
            style.map(style_name, background=[("active", hex_color)])

            ttk.Button(control_frame, text=f"{t}°C", command=lambda t=t: self.set_temperature(t),
                       style=style_name).pack(side="left", padx=5)

        self.custom_var = tk.DoubleVar()
        ttk.Entry(control_frame, textvariable=self.custom_var, width=7).pack(side="left", padx=5)
        ttk.Button(control_frame, text="Set Custom", command=lambda: self.set_temperature(self.custom_var.get())).pack(side="left", padx=5)

        # Run/Stop
        action_frame = ttk.Frame(self.root)
        action_frame.pack(pady=5)
        self.start_btn = ttk.Button(action_frame, text="Run Chamber", command=self.run_chamber, state="disabled")
        self.start_btn.pack(side="left", padx=10)
        self.stop_btn = ttk.Button(action_frame, text="Stop Chamber", command=self.stop_chamber, state="disabled")
        self.stop_btn.pack(side="left", padx=10)


        # Current Temp Display
        self.temp_label = ttk.Label(self.root, text="Current Temperature: -- °C", font=("Arial", 20))
        self.temp_label.pack(pady=5)

        # Plot area
        fig, ax = plt.subplots(figsize=(7,3))
        self.fig, self.ax = fig, ax
        self.line, = ax.plot([], [], label="Temp")
        ax.set_title("Temperature Over Time")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Temp (°C)")
        ax.grid(True)
        canvas = FigureCanvasTkAgg(fig, master=self.root)
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas = canvas

    def connect_chamber(self):
        ip = self.ip_var.get()
        try:
            self.chamber = ClimateChamber(ip=ip, temperature_min=-100, temperature_max=200)
            self.chamber.temperature_set_point = self.chamber.temperature_measured
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="normal")
            self.disconnect_btn.config(state="normal")
            messagebox.showinfo("Connected", f"Connected to chamber at {ip}")
        except Exception as e:
            messagebox.showerror("Connection Failed", str(e))

    def disconnect_chamber(self):
            if self.chamber:
                try:
                    self.chamber.stop_execution()
                except Exception:
                    pass
            self.chamber = None
            self.running = False
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="disabled")
            self.disconnect_btn.config(state="disabled")
            self.temp_label.config(text="Current Temp: -- °C")
            self.temperature_history.clear()
            self.time.clear()
            self.line.set_data([], [])
            self.canvas.draw()
            messagebox.showinfo("Disconnected", "Disconnected from chamber.")

    def set_temperature(self, t):
        if not self.chamber:
            return messagebox.showwarning("Not Connected", "Connect to chamber first.")
        try:
            self.chamber.temperature_set_point = t
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def run_chamber(self):
        if self.chamber and self.chamber.start_execution():
            self.running = True

    def stop_chamber(self):
        if self.chamber and self.chamber.stop_execution():
            self.running = False

    def update_plot(self):
        if self.chamber and self.running:
            try:
                self.chamber.retrieve_climate_chamber_status()
                temp = self.chamber.temperature_measured
                self.current_temperature = temp
                self.temperature_history.append(temp)
                self.time.append(len(self.time))
                self.temp_label.config(text=f"Current Temperature: {temp:.1f} °C")
            except Exception as e:
                print("Read error:", e)
        if self.time:
            self.line.set_data(self.time, self.temperature_history)
            self.ax.set_xlim(0, max(self.time))
            self.ax.set_ylim(min(self.temperature_history)-5, max(self.temperature_history)+5)
            self.canvas.draw()
        self.root.after(1000, self.update_plot)

def temperature_to_hex_color(temp, t_min=-40, t_max=85):
    """
    Linearly interpolate between blue and red.
    temp: current temperature
    returns: HEX color string
    """
    # Normalize temperature to 0–1
    ratio = (temp - t_min) / (t_max - t_min)
    ratio = max(0.0, min(1.0, ratio))

    # Interpolate between blue and red (in RGB)
    red = int(33 + (244 - 33) * ratio)  # from #2196F3 to #F44336
    green = int(150 + (67 - 150) * ratio)
    blue = int(243 + (54 - 243) * ratio)

    return f'#{red:02x}{green:02x}{blue:02x}'


if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=("Arial", 12), background="#f2f2f2")
    app = ThermalChamberGUI(root)
    root.mainloop()
