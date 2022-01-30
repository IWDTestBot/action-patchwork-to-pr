FROM blueztestbot/bluez-build:latest

COPY *.sh /
COPY *.py /
COPY *.json /

ENTRYPOINT ["/entrypoint.sh"]
