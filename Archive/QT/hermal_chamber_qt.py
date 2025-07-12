import sys
import random
import time
from threading import Thread
from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from colorsys import hsv_to_rgb


class WorkerSignals(QObject):
    temperature_updated = pyqtSignal(float)


class ChamberWorker(Thread):
    def __init__(self, signals):
        super().__init__()
        self.signals = signals
        self.running = True
        self.current_temp = 25.0
        self.target_temp = 25.0
        self.is_running = False

    def run(self):
        start_time = time.time()
        while self.running:
            elapsed_minutes = (time.time() - start_time) / 60
            if self.is_running:
                diff = self.target_temp - self.current_temp
                step = diff * 0.05 + random.uniform(-0.1, 0.1)
                self.current_temp += step
            else:
                self.current_temp += (25 - self.current_temp) * 0.01 + random.uniform(-0.05, 0.05)

            self.signals.temperature_updated.emit(self.current_temp)
            time.sleep(0.5)

    def stop(self):
        self.running = False


class ThermalChamberController(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        # Load the UI file
        uic.loadUi('thermal_chamber.ui', self)

        # Setup variables
        self.min_temp = -40
        self.max_temp = 150
        self.temp_range = self.max_temp - self.min_temp
        self.is_connected = False
        self.is_running = False

        # Setup worker thread
        self.signals = WorkerSignals()
        self.worker = ChamberWorker(self.signals)
        self.signals.temperature_updated.connect(self.update_temperature_display)
        self.worker.start()

        # Connect signals
        self.connectButton.clicked.connect(self.connect_chamber)
        self.disconnectButton.clicked.connect(self.disconnect_chamber)

        # Initialize temperature display labels (add these to your UI file if missing)
        self.currentTempLabel = QtWidgets.QLabel("25.0 °C")
        self.targetTempLabel = QtWidgets.QLabel("25.0 °C")

        # Add temperature displays to your layout (you may need to add containers in your UI file)
        temp_display_layout = QtWidgets.QHBoxLayout()
        temp_display_layout.addWidget(QtWidgets.QLabel("Current:"))
        temp_display_layout.addWidget(self.currentTempLabel)
        temp_display_layout.addWidget(QtWidgets.QLabel("Target:"))
        temp_display_layout.addWidget(self.targetTempLabel)

        # Add to main layout (adjust based on your UI structure)
        self.verticalLayout.insertLayout(0, temp_display_layout)

        # Setup plot
        self.setup_plot()

        # Apply dark theme
        self.apply_dark_theme()

    def get_temp_color(self, temp):
        """Get color for a specific temperature using HSV gradient"""
        normalized = (temp - self.min_temp) / self.temp_range
        hue = 0.66 * (1 - normalized)
        r, g, b = hsv_to_rgb(hue, 1.0, 0.7 + 0.3 * normalized)
        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

    def apply_dark_theme(self):
        """Apply dark theme styling"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121212;
            }
            QGroupBox {
                background-color: #1E1E1E;
                border: 1px solid #333;
                border-radius: 5px;
                margin-top: 10px;
                color: white;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                color: #BB86FC;
            }
            QLabel {
                color: white;
            }
            QPushButton {
                background-color: #3700B3;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 4px;
            }
            QPushButton:disabled {
                background-color: #333;
            }
            QComboBox {
                background-color: #1E1E1E;
                color: white;
                border: 1px solid #333;
                padding: 5px;
            }
        """)

    def setup_plot(self):
        """Initialize the matplotlib plot"""
        self.figure = Figure(facecolor='#1E1E1E')
        self.canvas = FigureCanvas(self.figure)

        # Add plot to the plotLayout from UI file
        plot_group = self.findChild(QtWidgets.QGroupBox, 'plotGroup')
        plot_layout = plot_group.layout()
        plot_layout.addWidget(self.canvas)

        self.ax = self.figure.add_subplot(111)
        self.ax.set_facecolor('#2E2E2E')
        self.ax.grid(True, linestyle='--', alpha=0.3, color='#555555')
        self.ax.set_xlabel('Time (minutes)', color='white')
        self.ax.set_ylabel('Temperature (°C)', color='white')
        self.ax.set_title('Temperature Profile', color='white')
        self.ax.set_ylim(self.min_temp, self.max_temp)
        self.ax.tick_params(colors='white')

        for spine in self.ax.spines.values():
            spine.set_edgecolor('#555555')

        self.x_data = []
        self.y_data = []
        self.line, = self.ax.plot([], [], color=self.get_temp_color(25), linewidth=2)

    def update_temperature_display(self, temp):
        """Update the temperature display"""
        self.currentTempLabel.setText(f"{temp:.1f} °C")
        self.currentTempLabel.setStyleSheet(f"color: {self.get_temp_color(temp)};")

        # Update plot
        self.x_data.append(len(self.x_data) * 0.5 / 60)  # Convert seconds to minutes
        self.y_data.append(temp)

        if len(self.x_data) > 100:
            self.x_data = self.x_data[-100:]
            self.y_data = self.y_data[-100:]

        self.line.set_data(self.x_data, self.y_data)
        self.line.set_color(self.get_temp_color(temp))
        self.ax.relim()
        self.ax.autoscale_view()
        self.canvas.draw()

    def connect_chamber(self):
        """Handle chamber connection"""
        ip = self.ipCombo.currentText()
        self.is_connected = True
        self.statusLabel.setText(f"Connected to {ip}")
        self.statusLabel.setStyleSheet(f"background-color: {self.get_temp_color(25)}; color: white;")
        self.connectButton.setEnabled(False)
        self.disconnectButton.setEnabled(True)
        self.ipCombo.setEnabled(False)

    def disconnect_chamber(self):
        """Handle chamber disconnection"""
        self.is_connected = False
        self.is_running = False
        self.statusLabel.setText("Disconnected")
        self.statusLabel.setStyleSheet("background-color: #CF6679; color: white;")
        self.connectButton.setEnabled(True)
        self.disconnectButton.setEnabled(False)
        self.ipCombo.setEnabled(True)

    def closeEvent(self, event):
        """Handle window close event"""
        self.worker.stop()
        self.worker.join()
        event.accept()


if __name__ == "__main__":
    # Handle Wayland session type
    if '--wayland' in sys.argv:
        sys.argv.remove('--wayland')

    app = QtWidgets.QApplication(sys.argv)
    window = ThermalChamberController()
    window.show()
    sys.exit(app.exec_())