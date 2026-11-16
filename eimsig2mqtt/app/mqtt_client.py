"""Dünne Hülle um paho-mqtt mit der Schnittstelle, die eimsig2mqtt braucht.

Funktioniert mit paho-mqtt 1.6 und 2.x (Alpine/Ubuntu liefern je nach Version das eine oder andere).
paho kümmert sich um Keepalive und automatische Neuverbindung.
"""
import threading

import paho.mqtt.client as paho


def _neuer_client(client_id):
    try:  # paho-mqtt >= 2.0
        return paho.Client(callback_api_version=paho.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        return paho.Client(client_id=client_id)


def _fehler(rc):
    """True, wenn der Rückgabecode einen Fehler bedeutet (int bei paho 1.x, ReasonCode bei 2.x)."""
    if hasattr(rc, "is_failure"):
        return rc.is_failure
    return rc != 0


class MQTT:
    def __init__(self, host, port=1883, user=None, password=None, client_id="eimsig2mqtt",
                 keepalive=60, will=None, log=print):
        self.host, self.port, self.keepalive, self.log = host, int(port), keepalive, log
        self.on_connect = None          # f()
        self.on_message = None          # f(topic, payload_bytes)
        self.subscriptions = []
        self._connected = threading.Event()
        self.c = _neuer_client(client_id)
        if user:
            self.c.username_pw_set(user, password or None)
        if will:
            self.c.will_set(will[0], will[1], qos=0, retain=will[2])
        self.c.reconnect_delay_set(min_delay=1, max_delay=60)
        self.c.on_connect = self._on_connect
        self.c.on_disconnect = self._on_disconnect
        self.c.on_message = self._on_message

    @property
    def connected(self):
        return self._connected.is_set()

    def start(self):
        self.c.connect_async(self.host, self.port, self.keepalive)
        self.c.loop_start()

    def subscribe(self, topic):
        if topic not in self.subscriptions:
            self.subscriptions.append(topic)
        if self.connected:
            self.c.subscribe(topic, qos=0)

    def publish(self, topic, payload, retain=False):
        """QoS 0. False, wenn gerade keine Verbindung besteht (Nachricht wird verworfen)."""
        if not self.connected:
            return False
        return self.c.publish(topic, payload, qos=0, retain=retain).rc == paho.MQTT_ERR_SUCCESS

    def stop(self, final=None):
        if self.connected:
            for t, p, r in final or []:
                info = self.c.publish(t, p, qos=0, retain=r)
                try:
                    info.wait_for_publish(timeout=2)
                except (RuntimeError, ValueError):
                    pass
        self.c.disconnect()
        self.c.loop_stop()

    # paho-Callbacks (Signaturen passen zu paho 1.x und 2.x)
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if _fehler(rc):
            self.log(f"MQTT: Verbindung abgelehnt ({rc})")
            return
        self._connected.set()
        self.log(f"MQTT verbunden mit {self.host}:{self.port}")
        for t in self.subscriptions:
            client.subscribe(t, qos=0)
        if self.on_connect:
            self.on_connect()

    def _on_disconnect(self, client, userdata, *args):
        self._connected.clear()
        rc = args[1] if len(args) >= 2 else (args[0] if args else 0)
        if _fehler(rc):
            self.log(f"MQTT getrennt ({rc}) – paho verbindet automatisch neu")

    def _on_message(self, client, userdata, msg):
        if self.on_message:
            try:
                self.on_message(msg.topic, msg.payload)
            except Exception as e:  # noqa: BLE001
                self.log(f"Fehler in on_message: {e}")
