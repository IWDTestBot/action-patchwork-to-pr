FROM blueztestbot/bluez-build:latest

COPY *.sh /
COPY *.py /
COPY *.json /
COPY *.txt /

ENTRYPOINT ["/entrypoint.sh"]
