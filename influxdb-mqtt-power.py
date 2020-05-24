#!/usr/bin/python
import os
import datetime
import threading
import time
import yaml
import logging
import paho.mqtt.client as mqtt
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError  # noqa
import pprint
import signal

if os.getenv('VERBOSE', 'false').lower() == 'true':
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.WARNING)


class Mqtt_Base():
    def __init__(self, *args, **kwargs):
        self._mqtt_connected = False
        return

    def _mqtt_subscribe(self, client):
        # Override me to create the subscriptions
        client.subscribe("$SYS/#")
        logging.info("MQTT Subscribed to $SYS/#")
        return

    def _mqtt_on_message(self, client, userdata, msg):
        # Override me to handle messages
        logging.warning("MQTT There is no method to handle mqtt messaged")
        logging.debug("MQTT received message {}".format(msg))
        return

    def _is_mqtt_connected(self):
        return self._mqtt_connected

    def _register_methods_to_client(self, client):
        client.on_connect = self._mqtt_on_connect
        client.on_disconnect = self._mqtt_on_disconnect
        client.on_message = self._mqtt_on_message
        client.on_log = self._mqtt_on_log
        return

    def _mqtt_on_connect(self, client, userdata, flags, rc):
        self._mqtt_connected = True
        logging.info("MQTT Connected with result code " + str(rc))

        self._mqtt_subscribe(client)

        return

    def _mqtt_on_disconnect(self, client, userdata, rc):
        logging.info("MQTT Disconnected with result code " + str(rc))
        return

    def _mqtt_on_log(self, client, userdata, level, buf):
        logging.info("MQTT: " + buf)
        return

    def _connect_mqtt(self, host, username, password, port=1883):
        # create mqtt connection
        self._mqtt_server = mqtt.Client("", True)

        self._register_methods_to_client(self._mqtt_server)
        if username is not None:
            self._mqtt_server.username_pw_set(username, password)        

        self._mqtt_server.connect(host, port, 60)
        self._mqtt_server.loop_start()
        return self._mqtt_server

    def _disconnect_mqtt(self):
        self._mqtt_server.disconnect()
        self._mqtt_server.loop_stop()
        return


class InfluxDBMeasurements():
    def __init__(self):
        self._collected_measurements = []
        self._collected_measurements_lock = threading.Lock()
        return

    def add_measurement(self, measurement):
        self._collected_measurements_lock.acquire()
        self._collected_measurements.append(measurement)
        self._collected_measurements_lock.release()
        return

    def flush_to_influxdb(self, client):
        # get the lock for the measurements and then write
        try:
            self._collected_measurements_lock.acquire()
            logging.debug("attempting to write the following data points to influxdb: {}".format(self._collected_measurements))
            client.write_points(self._collected_measurements)
            self._collected_measurements = []
        except ValueError as valueError:
            # bad data to influxDB, blow up for now
            raise valueError
        except Exception:
            # TODO: reconnect to influxdb
            logging.exception("Unable to write data to influxdb")
        finally:
            self._collected_measurements_lock.release()
        return


class Influxdb_Base():
    def __init__(self):
        self.influx_measurements = InfluxDBMeasurements()
        return

    def _is_influx_connected(self, dbname=None):
        is_connected = False

        if dbname is None:
            dbname = self._influx_dbname
        try:
            self._influx_client.ping()
            dblist = self._influx_client.get_list_database()
            if dbname in [x['name'] for x in dblist]:
                is_connected = True
            else:
                logging.debug("influx not connected: db {} not visible".format(dbname))
        except Exception as e:
            logging.debug("influx not connected: {}".format(e))

        return is_connected

    def _connect_influxdb(self, host, port, user, pw, dbname):
        # create connection to influxdb
        # Exceptions here are not caught, needs to be handled by above
        client = InfluxDBClient(host, port, user, pw, dbname)
        client.ping()
        logging.info('Connectivity to InfluxDB present')
        dblist = client.get_list_database()
        if dbname not in [x['name'] for x in dblist]:
            logging.info("Database doesn't exist, creating")
            client.create_database(dbname)

        logging.info('Connection to influxDB successful')

        self._influx_client = client
        self._influx_dbname = dbname

        return self._influx_client

    def _disconnect_influxdb(self):
        self._influx_client = None
        return

    def _flush_to_influxdb(self):
        # Take the accumulated measurements and send them to influxdb
        self.influx_measurements.flush_to_influxdb(self._influx_client)
        return

    def _add_influx_data_point(self, measurement_name, measurement_value, tags=None, time=None):
        # measurement value can be a number or a object eg 42.01 or {"power": 42.01, "hostname": "heartofgold"}
        """
        {
            "measurement": "cpu_load_short",
            "tags": {
                "host": "server01",
                "region": "us-west"
            },
            "time": "2009-11-10T23:00:00Z",
            "fields": {
                "value": 0.64
            }
        }
        """

        if not isinstance(measurement_value, dict):
            measurement_value = {
                "value": measurement_value
            }
        data_point = {
            'measurement': measurement_name,
            'fields': measurement_value,
            'tags': tags
        }
        if tags is not None:
            # should check format
            data_point['tags'] = tags
        if time is not None:
            # should check format
            data_point['time'] = time
        else:
            data_point['time'] = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

        self.influx_measurements.add_measurement(data_point)

        return


class MqttPower(Mqtt_Base, Influxdb_Base):
    def __init__(self, *args, **kwargs):

        self._mqtt_loads = []
        self._scheduled_loads = []
        self._state_cache = {}

        self._influx_client = None

        self._influx_conn_info = {
            "dbname": os.getenv('INFLUXDB_DATABASE', 'power'),
            "user": os.getenv('INFLUXDB_USER'),
            "password": os.getenv('INFLUXDB_PASSWORD'),
            "port": os.getenv('INFLUXDB_PORT', 8086),
            "host": os.getenv('INFLUXDB_HOST')
        }

        self._mqtt_conn_info = {
            "port": os.getenv('MQTT_PORT', 1883),
            "host": os.getenv('MQTT_HOST'),
            "user": os.getenv('MQTT_USER'),
            "password": os.getenv('MQTT_PASSWORD')
        }

        self._heartbeat_interval = os.getenv('INTERVAL', 10)
        self._heartbeat_exit = False

        # initialize the base class for mqtt and influx
        Mqtt_Base.__init__(self, *args, **kwargs)
        Influxdb_Base.__init__(self, *args, **kwargs)

        return

    def _connect_mqtt(self):
        # provide connection information from our config
        value = Mqtt_Base._connect_mqtt(self,
                                        self._mqtt_conn_info['host'],
                                        self._mqtt_conn_info['user'],
                                        self._mqtt_conn_info['password'],
                                        self._mqtt_conn_info['port'])
        return value

    def _connect_influxdb(self):
        # provide connection information from our config
        value = Influxdb_Base._connect_influxdb(self,
                                                self._influx_conn_info['host'],
                                                self._influx_conn_info['port'],
                                                self._influx_conn_info['user'],
                                                self._influx_conn_info['password'],
                                                self._influx_conn_info['dbname']
                                                )
        return value

    def _mqtt_subscribe(self, client):
        # Subscribe to the topics from mqtt requests
        for load in self._mqtt_loads:
            logging.info("MQTT subscribing to {}".format(load['topic']))
            client.subscribe((load['topic'], 2))
            if 'dimmer' in load.keys():
                logging.info("MQTT subscribing to {}".format(load['dimmer']['topic']))
                client.subscribe((load['dimmer']['topic'], 2))
        return

    def _mqtt_on_message(self, client, userdata, msg):
        # Add our values to the cache
        # TODO: refactor data point creation to allow registration for notification or similar to allow instantaneous data
        logging.debug("MQTT received on topic {} message {}".format(msg.topic, msg.payload))
        self._state_cache[msg.topic] = msg.payload
        return

    def heartbeat(self):

        while not self._heartbeat_exit:
            logging.debug("heartbeat")
            timestring = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

            self._add_static_values(timestring)
            self._add_state_values(timestring)

            # send data to influxdb
            self._flush_to_influxdb()
            time.sleep(self._heartbeat_interval)

    def _start_heartbeat(self):
        self._heartbeat_thread = threading.Thread(target=self.heartbeat)
        self._heartbeat_thread.daemon = True
        self._heartbeat_thread.start()
        return

    def _stop_heartbeat(self):
        self._heartbeat_exit = True
        self._heartbeat_thread.join()
        return

    def start(self):
        self.running = True
        self._connect_influxdb()
        self._connect_mqtt()
        self._start_heartbeat()
        return

    def stop(self, signum=None, frame=None):
        self._stop_heartbeat()
        self._disconnect_influxdb()
        self._disconnect_mqtt()
        self.running = False
        return

    def load_config_file(self, filename):
        # load the config from a file
        with open(filename) as fp:
            config = yaml.load(fp, Loader=yaml.FullLoader)
            self.load_config(config)

        return

    def load_config(self, configobj):
        # take a config and set it up
        self._scheduled_loads = configobj['scheduled_loads']
        self._mqtt_loads = configobj['mqtt_loads']
        for load in self._mqtt_loads:
            # initialize cache
            self._state_cache[load['topic']] = False
            if 'dimmer' in load.keys():
                self._state_cache[load['dimmer']['topic']] = 0
        return

    def _add_static_values(self, timestring):
        # publish all the values which don't depend on state
        for load in self._scheduled_loads:
            self._add_influx_data_point(
                load['measurement_name'],
                int(load['power']),
                time=timestring
            )
        return

    def _add_state_values(self, timestring):
        # publish all the values which depend on state
        for load in self._mqtt_loads:
            power = 0
            on = False
            logging.debug("Cached value for {} is {}".format(load['topic'], self._state_cache[load['topic']]))
            if isinstance(self._state_cache[load['topic']], (str, bytes)):
                if self._state_cache[load['topic']].lower() in ['on', 'true', b'on', b'true']:
                    on = True
            else:
                on = self._state_cache[load['topic']]

            if on:
                if 'dimmer' in load.keys():
                    power = int(load['power']) * int(self._state_cache[load['dimmer']['topic']]) / int(load['dimmer']['range'])
                    power = int(power)
                else:
                    power = int(load['power'])

            self._add_influx_data_point(
                load['measurement_name'],
                power,
                time=timestring
            )
        return


if __name__ == '__main__':
    power_obj = MqttPower()
    power_obj.load_config_file(os.getenv('CONFIG', '/config/config.yaml'))
    try:
        power_obj.start()
        signal.signal(signal.SIGINT, power_obj.stop)
        signal.signal(signal.SIGTERM, power_obj.stop)
        while power_obj.running:
            time.sleep(2)
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt")
        power_obj.stop()
    finally:
        logging.info("Shut Down")
        
