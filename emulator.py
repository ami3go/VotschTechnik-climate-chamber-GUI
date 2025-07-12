# --------------- chamber_emulator.py ---------------
import socket
import threading
import time
import random


class ClimateChamberEmulator:
    def __init__(self):
        self.temperature = 25.0
        self.humidity = 50.0
        self.temp_setpoint = 25.0
        self.hum_setpoint = 50.0
        self.running = False
        self.door_open = False
        self.alarm = False
        self.simulation_thread = threading.Thread(target=self.simulate, daemon=True)
        self.simulation_thread.start()

    def simulate(self):
        while True:
            time.sleep(1)
            if self.running:
                # Simulate temperature change
                temp_diff = self.temp_setpoint - self.temperature
                self.temperature += temp_diff * 0.1 + random.uniform(-0.2, 0.2)

                # Simulate humidity change
                hum_diff = self.hum_setpoint - self.humidity
                self.humidity += hum_diff * 0.1 + random.uniform(-0.5, 0.5)

                # Simulate door open events
                if random.random() < 0.05:  # 5% chance per second
                    self.door_open = True
                elif self.door_open and random.random() < 0.3:  # 30% chance to close
                    self.door_open = False

                # Simulate alarms
                if not self.alarm and random.random() < 0.01:  # 1% chance
                    self.alarm = True
                elif self.alarm and random.random() < 0.2:  # 20% chance to clear
                    self.alarm = False

    def handle_command(self, command):
        cmd = command.strip().upper()
        print(cmd)
        if cmd == "GET_TEMP":
            return f"OK:{self.temperature:.1f}"
        elif cmd == "GET_HUMIDITY":
            return f"OK:{self.humidity:.1f}"
        elif cmd == "GET_SETTINGS":
            return f"OK:TEMP={self.temp_setpoint:.1f},HUM={self.hum_setpoint:.1f}"
        elif cmd == "GET_STATUS":
            status = "RUNNING" if self.running else "STOPPED"
            door = "OPEN" if self.door_open else "CLOSED"
            alarm = "ALARM" if self.alarm else "OK"
            return f"OK:STATUS={status},DOOR={door},ALARM={alarm}"

        elif cmd.startswith("SET_TEMP"):
            try:
                temp = float(cmd.split()[1])
                if 0 <= temp <= 100:
                    self.temp_setpoint = temp
                    return "OK"
            except:
                pass
            return "ERROR:INVALID_TEMP"

        elif cmd.startswith("SET_HUMIDITY"):
            try:
                hum = float(cmd.split()[1])
                if 0 <= hum <= 100:
                    self.hum_setpoint = hum
                    return "OK"
            except:
                pass
            return "ERROR:INVALID_HUMIDITY"

        elif cmd == "START":
            self.running = True
            return "OK"

        elif cmd == "STOP":
            self.running = False
            return "OK"

        elif cmd == "RESET_ALARM":
            self.alarm = False
            return "OK"

        return "ERROR:UNKNOWN_COMMAND"


def start_server(host='localhost', port=2049):
    chamber = ClimateChamberEmulator()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((host, port))
    server.listen()
    print(f"Chamber emulator running on {host}:{port}")

    while True:
        client, addr = server.accept()
        print(f"New connection from {addr}")
        threading.Thread(target=handle_client, args=(client, chamber)).start()


def handle_client(client, chamber):
    with client:
        while True:
            try:
                data = client.recv(1024)
                if not data:
                    break
                command = data.decode().strip()
                response = chamber.handle_command(command) + "\n"
                client.sendall(response.encode())
            except ConnectionResetError:
                break
    print("Client disconnected")


if __name__ == "__main__":
    start_server()