FROM python:alpine
MAINTAINER brilthor <brilthor@gmail.com>

WORKDIR /src
COPY requirements.txt influxdb-mqtt-power.py /src/
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "-u", "/src/influxdb-mqtt-power.py"]