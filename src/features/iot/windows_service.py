"""Install/start the IoT gateway as a Windows Service using pywin32.

From the src directory, with elevation:
    python -m features.iot.windows_service install --startup auto
    python -m features.iot.windows_service start
"""

import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

from features.iot.gateway import IoTGateway


class AliceIoTGatewayService(win32serviceutil.ServiceFramework):
    _svc_name_ = "AliceIoTGateway"
    _svc_display_name_ = "Alice IoT Gateway"
    _svc_description_ = "MQTT ingestion, room device state, alerts and climate policy"

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.gateway = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.gateway is not None:
            threading.Thread(target=self.gateway.server.shutdown,
                             name="iot-service-stop", daemon=True).start()

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("Alice IoT Gateway starting")
        self.gateway = IoTGateway()
        try:
            self.gateway.run()
        finally:
            servicemanager.LogInfoMsg("Alice IoT Gateway stopped")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(AliceIoTGatewayService)
