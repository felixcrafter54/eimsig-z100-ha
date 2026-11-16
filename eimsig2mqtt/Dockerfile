ARG BUILD_FROM
FROM $BUILD_FROM

# Python, paho-mqtt und rtl-sdr (rtl_tcp für die USB-Quelle) aus den Alpine-Paketquellen
RUN apk add --no-cache python3 py3-paho-mqtt rtl-sdr

COPY app /app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
