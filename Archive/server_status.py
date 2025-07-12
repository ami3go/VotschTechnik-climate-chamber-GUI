# --------------- chamber_gui.py ---------------
import tkinter as tk
from tkinter import ttk, messagebox
import socket
import threading
import time


class ClimateChamberGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Climate Chamber Controller")
        self.root.geometry("500x400")
        self.connected = False

        self.create_widgets()
        self.setup_connection()

    def create_widgets(self):
        # Connection frame
        conn_frame = ttk.Frame(self.root, padding="10")
        conn_frame.grid(row=0, column=0, sticky="ew")

        ttk.Label(conn_frame, text="Server:").grid(row=0, column=0)
        self.server_entry = ttk.Entry(conn_frame, width=15)
        self.server_entry.grid(row=0, column=1, padx=5)
        self.server_entry.insert(0, "localhost:9999")

        self.connect_btn = ttk.Button(conn_frame, text="Connect", command=self.toggle_connection)
        self.connect_btn.grid(row=0, column=2, padx=5)

        # Status indicators
        status_frame = ttk.LabelFrame(self.root, text="Chamber Status", padding="10")
        status_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

        self.status_text = tk.Text(status_frame, height=8, width=50, state="disabled")
        self.status_text.pack(fill="both", expand=True)

        # Control panel
        control_frame = ttk.LabelFrame(self.root, text="Control Panel", padding="10")
        control_frame.grid(row=2, column=0, padx=10, pady=10, sticky="ew")

        ttk.Label(control_frame, text="Temperature (°C):").grid(row=0, column=0)
        self.temp_entry = ttk.Entry(control_frame, width=8)
        self.temp_entry.grid(row=0, column=1, padx=5)
        self.temp_entry.insert(0, "25.0")

        ttk.Button(control_frame, text="Set",
                   command=lambda: self.send_command(f"SET_TEMP {self.temp_entry.get()}")).grid(row=0, column=2, padx=5)

        ttk.Label(control_frame, text="Humidity (%):").grid(row=0, column=3, padx=(15, 0))
        self.hum_entry = ttk.Entry(control_frame, width=8)
        self.hum_entry.grid(row=0, column=4, padx=5)
        self.hum_entry.insert(0, "50.0")

        ttk.Button(control_frame, text="Set",
                   command=lambda: self.send_command(f"SET_HUMIDITY {self.hum_entry.get()}")).grid(row=0, column=5,
                                                                                                   padx=5)

        # Action buttons
        btn_frame = ttk.Frame(control_frame)
        btn_frame.grid(row=1, column=0, columnspan=6, pady=10)

        self.start_btn = ttk.Button(btn_frame, text="Start",
                                    command=lambda: self.send_command("START"), state="disabled")
        self.start_btn.pack(side="left", padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="Stop",
                                   command=lambda: self.send_command("STOP"), state="disabled")
        self.stop_btn.pack(side="left", padx=5)

        self.reset_btn = ttk.Button(btn_frame, text="Reset Alarm",
                                    command=lambda: self.send_command("RESET_ALARM"), state="disabled")
        self.reset_btn.pack(side="left", padx=5)

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

    def setup_connection(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.update_thread = threading.Thread(target=self.update_status, daemon=True)

    def toggle_connection(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def connect(self):
        try:
            address = self.server_entry.get().split(":")
            host = address[0]
            port = int(address[1]) if len(address) > 1 else 9999
            self.sock.connect((host, port))
            self.connected = True
            self.connect_btn.config(text="Disconnect")
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="normal")
            self.reset_btn.config(state="normal")
            self.update_thread.start()
            self.log_message("Connected to chamber server")
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect: {str(e)}")

    def disconnect(self):
        self.connected = False
        try:
            self.sock.close()
        except:
            pass
        self.connect_btn.config(text="Connect")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")
        self.reset_btn.config(state="disabled")
        self.log_message("Disconnected from server")
        self.setup_connection()  # Recreate socket for next connection

    def send_command(self, command):
        if not self.connected:
            messagebox.showwarning("Not Connected", "Please connect to the chamber server first")
            return

        try:
            self.sock.sendall(f"{command}\n".encode())
            response = self.sock.recv(1024).decode().strip()
            if response.startswith("OK"):
                self.log_message(f"Command successful: {command}")
            else:
                self.log_message(f"Error: {response}")
        except Exception as e:
            self.log_message(f"Communication error: {str(e)}")
            self.disconnect()

    def update_status(self):
        while self.connected:
            try:
                # Get temperature and humidity
                self.sock.sendall(b"GET_TEMP\n")
                temp = self.sock.recv(1024).decode().strip()

                self.sock.sendall(b"GET_HUMIDITY\n")
                hum = self.sock.recv(1024).decode().strip()

                self.sock.sendall(b"GET_STATUS\n")
                status = self.sock.recv(1024).decode().strip()

                # Update GUI
                self.root.after(0, self.update_display, temp, hum, status)
                time.sleep(1)
            except:
                if self.connected:
                    self.root.after(0, self.log_message, "Connection lost")
                    self.root.after(0, self.disconnect)
                break

    def update_display(self, temp, hum, status):
        if not self.connected:
            return

        # Parse responses
        try:
            temperature = temp.split(":")[1] if temp.startswith("OK:") else "N/A"
            humidity = hum.split(":")[1] if hum.startswith("OK:") else "N/A"

            if status.startswith("OK:"):
                status_parts = status[3:].split(",")
                status_dict = {part.split("=")[0]: part.split("=")[1] for part in status_parts}
            else:
                status_dict = {}
        except:
            temperature = "N/A"
            humidity = "N/A"
            status_dict = {}

        # Update status display
        self.status_text.config(state="normal")
        self.status_text.delete(1.0, tk.END)
        self.status_text.insert(tk.END, f"Temperature: {temperature} °C\n")
        self.status_text.insert(tk.END, f"Humidity: {humidity} %\n\n")
        self.status_text.insert(tk.END, f"Status: {status_dict.get('STATUS', 'N/A')}\n")
        self.status_text.insert(tk.END, f"Door: {status_dict.get('DOOR', 'N/A')}\n")
        self.status_text.insert(tk.END, f"Alarm: {status_dict.get('ALARM', 'N/A')}")

        # Apply status-based formatting
        self.status_text.tag_config("alarm", foreground="red")
        self.status_text.tag_config("running", foreground="green")

        if "ALARM" in status_dict and status_dict["ALARM"] == "ALARM":
            self.status_text.tag_add("alarm", "5.7", "5.end")

        if "STATUS" in status_dict and status_dict["STATUS"] == "RUNNING":
            self.status_text.tag_add("running", "3.7", "3.end")

        self.status_text.config(state="disabled")

    def log_message(self, message):
        self.status_text.config(state="normal")
        self.status_text.insert(tk.END, f"\n{message}")
        self.status_text.see(tk.END)
        self.status_text.config(state="disabled")


if __name__ == "__main__":
    root = tk.Tk()
    app = ClimateChamberGUI(root)
    root.mainloop()