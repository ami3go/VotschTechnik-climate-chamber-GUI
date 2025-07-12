import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import time
import tcam


# Dummy function to simulate reading temperature from hardware
def get_current_temperature():
    # Replace this with actual hardware reading
    return tcam.get_temperature()
    # return round(25 + (time.time() % 10), 1)  # Simulates fluctuating temperature


# Function to update the temperature display and plot
def update_temperature():
    current_temp = get_current_temperature()
    temp_label.config(text=f"Current Temperature: {current_temp}°C")

    # Update plot
    x_data.append(len(x_data))
    y_data.append(current_temp)

    # Keep only the last 60 data points
    if len(x_data) > 60:
        x_data.pop(0)
        y_data.pop(0)

    line.set_xdata(x_data)
    line.set_ydata(y_data)
    ax.relim()
    ax.autoscale_view()
    canvas.draw()

    root.after(1000, update_temperature)  # Schedule next update in 1 second


def set_temperature(temp):
    print(f"Setting temperature to {temp}°C")
    tcam.set_temperature(temp)


def run_chamber():
    tcam.run()
    print("Running chamber")


def stop_chamber():
    tcam.stop()
    print("Stopping chamber")


def custom_temp():
    temp = custom_entry.get()
    try:
        temp = float(temp)
        set_temperature(temp)
    except ValueError:
        print("Please enter a valid number")


# Create the main window
tcam.init()
root = tk.Tk()
root.title("Thermal Chamber Control")
root.geometry("800x600")
root.resizable(False, False)  # Disable resizing
root.configure(bg="#f0f0f0")

# Create a style for modern look
style = ttk.Style()
style.configure("TButton", font=("Helvetica", 12), padding=6, relief="flat", borderwidth=0)
style.configure("TEntry", font=("Helvetica", 12), padding=6)
style.configure("TLabel", font=("Helvetica", 12))

# Temperature display
temp_label = ttk.Label(root, text="Current Temperature: 25.0°C", font=("Helvetica", 14), foreground="blue")
temp_label.pack(pady=10)

# Create a frame for buttons (2 rows)
btn_frame = ttk.Frame(root)
btn_frame.pack(pady=20)

# Row 1
row1_frame = ttk.Frame(btn_frame)
row1_frame.pack()
ttk.Button(row1_frame, text="Set to -40°C", command=lambda: set_temperature(-40), style="TButton").pack(side="left",
                                                                                                        padx=10,
                                                                                                        ipadx=10,
                                                                                                        ipady=5)
ttk.Button(row1_frame, text="Set to +25°C", command=lambda: set_temperature(25), style="TButton").pack(side="left",
                                                                                                       padx=10,
                                                                                                       ipadx=10,
                                                                                                       ipady=5)
ttk.Button(row1_frame, text="Set to +60°C", command=lambda: set_temperature(60), style="TButton").pack(side="left",
                                                                                                       padx=10,
                                                                                                       ipadx=10,
                                                                                                       ipady=5)

# Row 2
row2_frame = ttk.Frame(btn_frame)
row2_frame.pack()
ttk.Button(row2_frame, text="Set to +85°C", command=lambda: set_temperature(85), style="TButton").pack(side="left",
                                                                                                       padx=10,
                                                                                                       ipadx=10,
                                                                                                       ipady=5)
ttk.Button(row2_frame, text="Run Chamber", command=run_chamber, style="TButton").pack(side="left", padx=10, ipadx=10,
                                                                                      ipady=5)
ttk.Button(row2_frame, text="Stop Chamber", command=stop_chamber, style="TButton").pack(side="left", padx=10, ipadx=10,
                                                                                        ipady=5)

# Custom temperature entry
custom_frame = ttk.Frame(root)
custom_frame.pack(pady=10)

ttk.Label(custom_frame, text="Custom Temperature (°C):", style="TLabel").pack(side="left")
custom_entry = ttk.Entry(custom_frame, width=10)
custom_entry.pack(side="left", padx=5)
ttk.Button(custom_frame, text="Set", command=custom_temp, style="TButton").pack(side="left")

# Plot setup
fig, ax = plt.subplots(figsize=(6, 3))
ax.set_title("Temperature Over Time")
ax.set_xlabel("Time (s)")
ax.set_ylabel("Temperature (°C)")
ax.grid(True)

x_data = []
y_data = []
line, = ax.plot([], [], 'b-')

canvas = FigureCanvasTkAgg(fig, master=root)
canvas.draw()
canvas.get_tk_widget().pack(pady=10)

# Start the temperature update loop
update_temperature()

# Start the GUI loop
root.mainloop()