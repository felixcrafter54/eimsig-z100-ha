#!/usr/bin/with-contenv bashio
# Startet eimsig2mqtt.
#  - MQTT: aus den Add-on-Optionen, sonst vom Mosquitto-Add-on (Service-Discovery)
#  - Quelle: externer rtl_tcp im Netz, oder RTL-SDR-Stick per USB (dann läuft rtl_tcp hier im Container)
set -e

if bashio::config.has_value 'mqtt_host'; then
    export MQTT_HOST="$(bashio::config 'mqtt_host')"
    export MQTT_PORT="$(bashio::config 'mqtt_port' 1883)"
    export MQTT_USER="$(bashio::config 'mqtt_user' '')"
    export MQTT_PASSWORD="$(bashio::config 'mqtt_password' '')"
    bashio::log.info "MQTT aus der Konfiguration: ${MQTT_HOST}:${MQTT_PORT}"
elif bashio::services.available 'mqtt'; then
    export MQTT_HOST="$(bashio::services 'mqtt' 'host')"
    export MQTT_PORT="$(bashio::services 'mqtt' 'port')"
    export MQTT_USER="$(bashio::services 'mqtt' 'username')"
    export MQTT_PASSWORD="$(bashio::services 'mqtt' 'password')"
    bashio::log.info "MQTT vom Mosquitto-Add-on: ${MQTT_HOST}:${MQTT_PORT}"
else
    bashio::exit.nok "Kein MQTT-Broker gefunden. Mosquitto-Add-on installieren oder mqtt_host in der Konfiguration setzen."
fi

if [ "$(bashio::config 'quelle')" = "usb" ]; then
    GERAET="$(bashio::config 'usb_geraet' 0)"
    bashio::log.info "Quelle: RTL-SDR per USB (Gerät ${GERAET}) – starte lokalen rtl_tcp (experimentell)"
    rtl_tcp -a 127.0.0.1 -p 1234 -d "${GERAET}" &
    sleep 2
    export RTL_TCP_HOST=127.0.0.1
    export RTL_TCP_PORT=1234
else
    if ! bashio::config.has_value 'rtl_tcp_host'; then
        bashio::log.warning "Keine rtl_tcp-Adresse eingetragen (Tab Konfiguration → rtl_tcp_host)."
    fi
    bashio::log.info "Quelle: rtl_tcp $(bashio::config 'rtl_tcp_host'):$(bashio::config 'rtl_tcp_port')"
fi

export EIMSIG_VERSION="$(bashio::addon.version)"
export EIMSIG_OPTIONS=/data/options.json
export EIMSIG_DATA=/data

exec python3 -u /app/eimsig2mqtt.py
