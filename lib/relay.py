## --------------------------------------------------------------------
## relay management
##
## Original Author   : Yaron Weinsberg
## 
## License   : GPL Version 3
## --------------------------------------------------------------------
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 3 of the License, or
## (at your option) any later version.
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
## --------------------------------------------------------------------

# This code is based on Yaron Weinsberg ' boiler controller ' code (https://github.com/wyaron/BoilerPlate)

import sys
import warnings
import time
from threading import Timer
import RPi.GPIO as GPIO
import logging

# our relay is controlled via GPIO pin 16 (BCM)
CTL_OUT = 16
    
def init_relay():       
    # switch to BCM
    # GPIO.setmode(GPIO.BCM)

    # disable warning of used ports
    # GPIO.setwarnings(False)

    # set the port as output port
    #GPIO.setup(CTL_OUT, GPIO.OUT)
    print('relay init')
    
def start_relay():
    GPIO.setup(CTL_OUT, GPIO.OUT)
    GPIO.output(CTL_OUT, GPIO.HIGH)
    logging.getLogger('RelayLogger').debug('relay is on')

def stop_relay():
    GPIO.setup(CTL_OUT, GPIO.OUT)
    GPIO.output(CTL_OUT, GPIO.LOW)
    logging.getLogger('RelayLogger').debug('relay is off')

def cleanup():
    logging.getLogger('RelayLogger').debug('cleanup GPIO system')
    GPIO.setup(CTL_OUT, GPIO.OUT)
    GPIO.cleanup()

def is_output_high():
    GPIO.setup(CTL_OUT, GPIO.OUT)
    return GPIO.input(CTL_OUT)

def test_relay():
   """Test relay on and off cycle"""
   
   # check if the output is high
   print('current control output is: ' + is_output_high() + ' (should be off)')

   # start the relay
   start_relay()

   print('current control output is: ' +  is_output_high() +' (should be on)')
   
   # setup a timer to stop the relay after 5 seconds
   t = Timer(5, stop_relay)
   t.start()

   # wait for the timer to finish
   t.join()   

if __name__ == '__main__': 
    init_relay()
    test_relay()
    cleanup()