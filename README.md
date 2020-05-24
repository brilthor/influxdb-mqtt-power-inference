# influxdb-mqtt-power-inference
Create time-series data based on states from MQTT for known load sizes.  Some other workarounds for influxdb limitations too

Some initial code (including the basis of this readme) grabbed from https://github.com/atribe/apcupsd-influxdb-exporter



## How to build
Building the image:
* Git clone this repo
* `docker build -t influxdb-mqtt-power  .`

## Environment Variables
These are all the available environment variables, along with some example values, and a description.

| Environment Varialbe | Example Value | Description |
| -------------------- | ------------- | ----------- |
| MQTT_HOST | 192.168.1.100 | MQTT Server  |
| MQTT_PORT | 1883 | MQTT Server port (defautls to 1883) |
| MQTT_USER | myuser | optional, defaults to empty |
| MQTT_PASSWORD | pass | optional, defaults to empty |
| INFLUXDB_HOST | 192.168.1.101 | host running influxdb |
| INFLUXDB_DATABASE | power | db name for influxdb. optional, defaults to power |
| INFLUXDB_USER | myuser | optional, defaults to empty |
| INFLUXDB_PASSWORD | pass | optional, defaults to empty |
| INFLUXDB_PORT |  8086 | optional, defaults to 8086 |
| INTERVAL | 10 | optional, defaults to 10 seconds |
| VERBOSE | true | if anything but true docker logging will show no output |
| CONFIG | /config/config.yaml | Path to config file defaults to /config/config.yaml |

## How to Use

Make sure you have a config file created, eg:
```
scheduled_loads:
  - measurement_name: "my_perpetual"
    power: 48
mqtt_loads:
  - measurement_name: "my_switch"
    topic: "mqtt_topic/for/on/off"
    power: 76
  - measurement_name: "my_dimmer"
    topic: "mqtt_topic/for/on/off"
    dimmer:
      topic: "mqtt_topic/for/dim_value"
      range: 255
    power: 86
```

### Run docker container directly
```bash
docker run --rm  -d --name="influxdb-mqtt-power" \
    -e "INFLUXDB_HOST=10.0.1.11" \
    -e "MQTT_HOST=10.0.1.11" \
    -v $(pwd)/config.yaml:/config/config.yaml\
    -t brilthor/influxdb-mqtt-power
```


### Run from docker-compose
```bash
version: '3'
volumes:
  config:
services:
  influxdb-mqtt-power:
    image: brilthor/influxdb-mqtt-power
    restart: always
    environment:
      MQTT_HOST: 10.0.1.11
      INFLUXDB_HOST: 10.0.1.11
      INTERVAL: 5
```

If you want see the debug logging, set the environment variable "VERBOSE" to "true"
