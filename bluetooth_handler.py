import threading
import asyncio
import time
import logging
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError
from config import DEVICE_NAME, STREAM_UUID, CMD_UUID

class BluetoothHandler:
    def __init__(self, msg_queue, processor):
        self.msg_queue = msg_queue
        self.processor = processor
        self.is_running = False
        self.logger = logging.getLogger("SensorApp.Bluetooth")

    def start(self):
        if self.is_running: return
        self.is_running = True
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._ble_task())

    async def _ble_task(self):
        self.logger.info("Automatischer Verbindungsmodus gestartet.")
        
        while True:
            self.msg_queue.put(("STATUS", ("🟡 Suche...", "warning")))
            try:
                devices = await BleakScanner.discover(timeout=5.0)
            except BleakError as e:
                self.logger.error(f"Bluetooth-Adapter Fehler: {e}")
                self.msg_queue.put(("STATUS", ("🔴 Adapter-Fehler", "danger")))
                await asyncio.sleep(5)
                continue
            except Exception as e:
                self.logger.error(f"Scan-Fehler: {e}")
                await asyncio.sleep(5)
                continue

            target = next((d for d in devices if d.name == DEVICE_NAME), None)

            if not target:
                self.msg_queue.put(("STATUS", ("🔴 Nicht gefunden", "danger")))
                await asyncio.sleep(3)
                continue

            self.logger.info(f"Gefunden: {target.address}. Verbinde...")
            self.msg_queue.put(("STATUS", ("🟡 Verbinde...", "warning")))
            
            def on_disconnect(client):
                self.logger.warning("Verbindung abgebrochen. Versuche Neustart...")
                self.msg_queue.put(("STATUS", ("🔴 Getrennt", "danger")))
                if self.processor.file:
                    self.processor.close_session()

            try:
                async with BleakClient(target, disconnected_callback=on_disconnect) as client:
                    self.logger.info("🟢 Verbunden! Warte auf Tasterdruck...")
                    self.msg_queue.put(("STATUS", ("🟢 Verbunden", "success")))

                    last_heartbeat = time.time()

                    def handle_cmd(sender, data):
                        nonlocal last_heartbeat
                        msg = data.decode('utf-8').strip()
                        
                        if msg == "HB":
                            last_heartbeat = time.time()
                            return
                            
                        if msg.startswith("INFO:") or msg.startswith("WARN:") or msg.startswith("ERR:"):
                            self.logger.info(f"Arduino: {msg}")
                        elif msg.startswith("START:"):
                            sec = int(msg.split(":")[1])
                            self.processor.start_session(sec)
                            self.msg_queue.put(("START_MEASURE", sec))
                        elif msg == "END":
                            if self.processor.close_session():
                                self.msg_queue.put(("END_MEASURE", self.processor.current_filepath))

                    def handle_stream(sender, data):
                        avg, complete, mbar_chunk = self.processor.process_chunk(data)
                        if mbar_chunk:
                            self.msg_queue.put(("LIVE_DATA", mbar_chunk))
                        if complete:
                            if self.processor.close_session():
                                self.msg_queue.put(("END_MEASURE", self.processor.current_filepath))

                    await client.start_notify(CMD_UUID, handle_cmd)
                    await client.start_notify(STREAM_UUID, handle_stream)

                    while client.is_connected:
                        await asyncio.sleep(1)
                        if time.time() - last_heartbeat > 5.0:
                            self.logger.error("Heartbeat Timeout! Verbindung verloren. Suche neu...")
                            await client.disconnect()
                            break
                        
            except BleakError as e:
                self.logger.error(f"Bluetooth-Verbindungsfehler: {e}")
                self.msg_queue.put(("STATUS", ("🔴 Fehler", "danger")))
                await asyncio.sleep(3)
            except Exception as e:
                self.logger.error(f"Unerwarteter Fehler: {e}")
                self.msg_queue.put(("STATUS", ("🔴 Fehler", "danger")))
                await asyncio.sleep(3)