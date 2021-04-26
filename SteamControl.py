#!/usr/bin/env python3

import relay
import max6675
import threading
from threading import Lock
from flask_socketio import SocketIO, emit
from flask import Flask, g, render_template

from datetime import datetime
import logging
import statistics
# import max6675 module.

import os
import sys
from pathlib import Path
sys.path.append(os.path.join(os.path.dirname(__file__), "lib"))

# get the relay functionality
import relay 

# temprature sensor related (global) values
cs = 19
sck = 33
so = 8

config_file_name = "/home/pi/SteamControl/config.txt"
# system main parameters/values:
# latest read value from temp sensor:
temp = 'N/A'

# cooling system CURRENT state (depending on prev state and avg temp read)
cooling_state = 'Off'


log = logging.getLogger('SteamControl')
log.setLevel(logging.ERROR)

async_mode = None
app = Flask(__name__)


socketio = SocketIO(app, async_mode=async_mode,
                    temp=temp, cooling_state=cooling_state)
thread = None
thread_lock = Lock()


def turn_on_cooling():
    global cooling_state

    print("in turn on func, cooling state is: " + cooling_state)
    if cooling_state == 'Off':

        # sanity check
        cooling_is_on = relay.is_output_high()  # read from relay (HW)
        if cooling_is_on:
            # this is bad may indicate a serious bug
            logging.getLogger('RelayLogger').debug(
                'Turn-On was called when already cooling is on. cleanup GPIO system')
            print("Turn-On was called when cooling is already on!")

            #notify_phone.send_push_mesage('potential bug: relay is on when turn_on_cooling is called', datetime.now())
            # stop_and_exit()
        else:
            relay.start_relay()
            #notify_phone.send_push_mesage('cooling is ON', datetime.now())
            #send_email(EMAIL_TO, EMAIL_SUBJECT, 'Cooling is turned ON! \n\n time: %s\n\n' %  str(datetime.now()))
            print("turning on cooling system")
            cooling_state = 'On'


def turn_off_cooling():
    global cooling_state

    print("in turn off func, cooling state is: " + cooling_state)
    if cooling_state == 'On':
        # sanity check
        cooling_is_on = relay.is_output_high()  # read from relay (HW)
        if not cooling_is_on:
            # this is bad may indicate a serious bug
            logging.getLogger('RelayLogger').debug(
                'Turn-Off was called when already cooling is off. cleanup GPIO system')
            print("Turn-Off was called when already cooling is off!")
            #notify_phone.send_push_mesage('potential bug: relay is off when stop_boiler is called', datetime.now())
            # stop_and_exit()
        else:
            relay.stop_relay()
            #
            # notify_phone.send_push_mesage('Cooling is turned OFF @ min' , datetime.now())
            #send_email(EMAIL_TO, EMAIL_SUBJECT, 'Cooling is turned OFF! \n\n time: %s\n\n' %  str(datetime.now()))
            print("turning off cooling system")
            cooling_state = 'Off'


def initSensor():
    # set the pin for communicate with MAX6675
    # max6675.set_pin(CS, SCK, SO, unit)   [unit : 0 - raw, 1 - Celsius, 2 - Fahrenheit]
    max6675.set_pin(cs, sck, so, 1)


def format_sample_time(t):
    return (str(t.hour).zfill(2) + ':' + str(t.minute).zfill(2) + ':' + str(t.second).zfill(2))


def calc_avg_temp(temp_samples):
    std = statistics.stdev(temp_samples)
    avg = statistics.mean(temp_samples)
    cleaned_samples = []
    for temp in temp_samples:
        if (temp > avg - std) and (temp < avg + std):
            cleaned_samples.append(temp)
    if len(cleaned_samples) < 2:
        return -1, False
    final_avg = statistics.mean(cleaned_samples)

    orglen = len(temp_samples)
    length = len(cleaned_samples)

    # print("avg: " + str(avg) + ", std: " +
    #       str(std) + ", final avg: " + str(final_avg) + ", original list length: " + str(orglen) + ", final list length: " + str(length))
    return final_avg, True


def read_config():
    # No validity checks etc... we assume (not safe!) that the config file contains two lines each with a valid temprature value
    with open(config_file_name, 'r') as conf:
        l = conf.readline()
        cooling_start_thresh = float(l)
        l = conf.readline()
        cooling_stop_thresh = float(l)
    return cooling_start_thresh, cooling_stop_thresh


# ========================================================================================================================
# Global vars that are updated in temprature_handling_thread, and are used for display at handle_client_thread.
# This way every connection has access to *global current data* and will not start its own reading loop from the sensor.
sample_index = 0
scale_graph_header = ''
short_graph_header = ''
sample_interval = 3
samples_window = (1 * 60 * 60 // sample_interval)
aggregated_index = 0
graph_points = 10
temprature_string = 'N/A'
# Threshold to start the cooling system
cooling_stop_thresh = 26

# Threshold to turn off the cooling system
cooling_start_thresh = 35

# ========================================================================================================================


# Every connection to the server will start this thread. It display the graphs and takes the data from GLOBAL vars thus
# the data is available immediately as its already in the measurements buffers.
def handle_client_thread():
    counter = 0
    while True:
        socketio.emit('update_state',
                      {'temp': temprature_string,
                       'threshold_on': str(cooling_start_thresh),
                       'threshold_off': str(cooling_stop_thresh),
                       'cooling': cooling_state})
        if (counter % 10 == 0):
            socketio.emit('update_long_graph', {
                'title': scale_graph_header, 'labels': aggregated_samples_time[0:aggregated_index], 'samples': aggregated_buffer[0:aggregated_index]})

        first_sample_in_graph = max(0, sample_index - graph_points)
        if (counter % 2 == 0):
            socketio.emit('update_short_graph', {
                'title': short_graph_header,  'labels': samples_time[first_sample_in_graph:sample_index], 'samples': temprature_buffer[first_sample_in_graph:sample_index]})

        counter = counter + 1
        socketio.sleep(sample_interval)


# Main thread.
# Sample temprature sensor every 'sample_interval' secoonds
# collect samples into temprature_buffer, along with proper lables vector
# If the total sampled time is T, and the display is capable to display D points, then
# every [T/sample_interval /D] samples we collect an average over the last [T/sample_interval /D] samples
# so that we have two sample buffers: one that has a sample per sample interval, and we take only the last D
# samples of it and display it as a short graph.
# the second buffer has averages taken over last total/D samples. Thus every point in the graph, among the maximall D points
# that can be displayed is average over the last total/D points. This will allow a "longer" perspective over the measurements.
#
def temprature_handling_thread():
    """Read temprature, process and display"""
    global sample_interval
    sample_interval = 3  # timeout between temprature sampling

    global sample_index
    global scale_graph_header
    global short_graph_header
    global samples_window
    global temprature_buffer
    global samples_time
    global aggregated_buffer
    global aggregated_samples_time
    global temprature_string
    global graph_points

    # moving window of 1 hour
    samples_window = (1 * 60 * 60 // sample_interval)
    # total of two hours will be stored, to be able to display a full one hour of data at any point
    total_samples = 2 * samples_window

    temprature_buffer = []
    samples_time = []

    aggregated_buffer = []
    aggregated_samples_time = []

    rotate_short = False
    average_temp_candidates = 4
    # read config for the first time (stop/start thresholds)
    global cooling_start_thresh
    global cooling_stop_thresh
    cooling_start_thresh, cooling_stop_thresh = read_config()

    # how many points in the graph can we safely/cleanly display
    graph_points = 60

    # calculate per how many regular samples we will take average for the "large graph"
    aggregation_factor = (total_samples // graph_points)
    short_graph_header = 'Temprature Recent History Graph: last ' + \
        str(graph_points * sample_interval // 60) + ' minutes'
    scale_graph_header = 'Temprature Recent History Graph: last up to  ' + \
        str((total_samples * 3) // 60) + ' minutes'

    with open("./temp_log.txt", 'a+') as f:
        f.write("\n\n{0} ============== Starting temprature logging ==============\n".format(
                datetime.now()))
        f.flush()
        while True:
            try:
                # read temperature connected at CS 19
                tempFloat = max6675.read_temp(cs)
                temprature_string = str(tempFloat)
                # when there are some errors with sensor, it return "-" sign and CS pin number
                # in this case it returns "-19"
                if tempFloat == -cs:
                    continue

                temprature_buffer.append(tempFloat)

                t = datetime.now()
                sample_time_string = format_sample_time(t)
                samples_time.append(cooling_state + '@' + sample_time_string)
                if (sample_index % aggregation_factor == 0) and (sample_index > 0):
                    avg_on_previous_batch, ok = calc_avg_temp(
                        temprature_buffer[sample_index - aggregation_factor:sample_index])
                    if ok:
                        aggregated_buffer.append(avg_on_previous_batch)
                        aggregated_samples_time.append(sample_time_string)
                        global aggregated_index
                        aggregated_index = aggregated_index + 1
                        if aggregated_index == graph_points:
                            aggregated_buffer = aggregated_buffer[graph_points // 2:]
                            aggregated_samples_time = aggregated_samples_time[graph_points // 2:]
                            aggregated_index = aggregated_index // 2
                sample_index = (sample_index+1) % total_samples

                if sample_index == 0:
                    # cyclic buffer... need to shift the last day's samples to the first half of the buffer.
                    rotate_short = True
                # Now do the real work: calc avg of last average_temp_candidates temp samples. If avg is above start-threshold then start the cooling system
                # and if the avg is below the off-threshold then turn the cooling sytem off
                # calc average on minimum of 'average_temp_candidates' elements.
                if sample_index >= average_temp_candidates:
                    avg, ok = calc_avg_temp(
                        temprature_buffer[sample_index-average_temp_candidates:sample_index])
                    if ok:
                        if avg > cooling_start_thresh:
                            turn_on_cooling()
                        if avg < cooling_stop_thresh:
                            turn_off_cooling()
            except KeyboardInterrupt:
                temprature_string = "N/A"
            f.write("{0} @ {1}\n".format(
                datetime.now(), temprature_string))
            f.flush()
            # following was moved to 'handle_client_thread' that is started per new connection
            # emit update_state
            # if enough time passed (e.g. 15 sec)
            #       emit('update_short_graph
            if rotate_short:
                # "shift left" the second half of the samples to the first half of the sample buffer and
                # continue to push new values to the seond half of the buffer.
                temprature_buffer = temprature_buffer[samples_window:]
                samples_time = samples_time[samples_window:]
                sample_index = samples_window
                rotate_short = False
            socketio.sleep(sample_interval)


@ app.route('/')
def index():
    return render_template('index.html', async_mode=socketio.async_mode, cooling_state=cooling_state, temp=temp)


def update_config_file():
    global cooling_start_thresh
    global cooling_stop_thresh
    stop_str = str(cooling_stop_thresh) + "\n"
    start_str = str(cooling_start_thresh) + "\n"

    print("\nUpdating config:")
    print("cooling on: " + start_str + "cooling off: " + stop_str)

    with open(config_file_name, 'w') as conf:
        conf.write(start_str)
        conf.write(stop_str)


@ socketio.event
def temp_thresh_on(message):
    global cooling_start_thresh
    prev_val = cooling_start_thresh
    if message['data'] != "":
        try:
            cooling_start_thresh = float(message['data'])
            if cooling_start_thresh > cooling_stop_thresh:
                update_config_file()
            else:
                cooling_start_thresh = prev_val
        except ValueError:
            pass


@ socketio.event
def temp_thresh_off(message):
    global cooling_stop_thresh
    prev_val = cooling_stop_thresh

    if message['data'] != "":
        try:
            cooling_stop_thresh = float(message['data'])
            if cooling_stop_thresh < cooling_start_thresh:
                update_config_file()
            else:
                cooling_stop_thresh = prev_val
        except ValueError:
            pass


@ socketio.event
def connect():
    global thread
    with thread_lock:
        if thread is None:
            thread = socketio.start_background_task(handle_client_thread)


@ socketio.event
def disconnect():
    print('disconnect ')


if __name__ == '__main__':
    initSensor()
    x = threading.Thread(target=temprature_handling_thread)
    x.start()
    relay.stop_relay()
    socketio.run(app, '0.0.0.0')
