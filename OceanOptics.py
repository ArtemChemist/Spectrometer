#!/usr/bin/env python -w
# -*- coding: UTF-8 -*-

# python module to communicate with an Ocena Optics USB spectrometer
#
# Based on the original 2012 work by
# Wolfgang Schoenfeld (wolfgang.schoenfeld@hzg.de) and
# Carsten Frank       (carsten.frank@hzg.de)
# also based on the documentation given in the USB4000-OEM_Data-Sheet.pdf
# which is publicly available (http://www.oceanoem.com/).
#
# This module is suitable to control a Avantes USB spectrometer.
# The following types are supported:
# - USB 4000
# - probably USB 2000

import os
import os.path
import re
import time
import sys
import numpy as np
import multiprocessing
import ctypes

sys.path.append('/home/carsten/Programme/python/FiaSia')
sys.path.append('/home/carsten/Programme/python')

from findUSBserialDevice import getDeviceFileFromAddress, testAddress

import usb.core, usb.util

USB_USBSPEC_VENDOR_ID = 0x2457
USB_USBSPEC_PRODUCT_ID_USB4000 = 0x1022
USB_USBSPEC_PRODUCT_ID_USB650 = 0x1014   # not working, kept for future use
PIXEL_COUNT_USB4000 = 3840

class USB4000: ## GUI OoUSB4000 ## Adds this device to the spectrometers listed in the GUI
    """Connect to a Ocean Optics mini spectrometer via USB.
    """

    # device name should be either the USB-address or the serial numer
    def __init__(self, deviceName = None):
        # the device name would be the 'device' in the "/dev/" folder (linux)
        self.deviceName   = None
        self.serialNumber = None

        # Only needed for pyUSB. Checks if the configuration was already set.
        self.configurationSet = False

        # self.usedInterface is set in findAllConnectedSpectrometers
        # self.usedInterface equals None if no device is found
        devNotFound = True

        # If no spectrometer is foud this function complains and exits!
        self.specs = self._findAllConnectedSpectrometers()

        if self.usedInterface == 'pyusb':
                if  deviceName == None:
                        # use the 'first' spectrometer
                        self.serialNumber = self.specs.keys()[0]
                        self.deviceName   = None
                        self.basePath     = None
                        devNotFound = False
                else:
                        # only the serial number would be delivered as device name in this context (pyusb)
                        if self.specs.has_key(deviceName):
                                self.serialNumber = key
                                self.deviceName   = None
                                self.basePath     = None
                                devNotFound       = False

        elif self.usedInterface == 'kernel':
                if  deviceName == None:
                        # use random device (if more than one device is attached)
                        self.serialNumber = self.specs.keys()[0]
                        self.deviceName = self.specs[self.serialNumber][0]
                        self.basePath = os.path.join("/sys/bus/usb/drivers/usbhspec/", self.specs[self.serialNumber][1])
                        devNotFound = False
                else:
                        # if it is an valid usb address like '8-2:1.0'
                        if testAddress(deviceName):
                                for key, value in self.specs.iteritems():
                                        if value[1] == deviceName:
                                                self.deviceName = value[0]
                                                self.basePath = os.path.join("/sys/bus/usb/drivers/usbhspec/", value[1])
                                                devNotFound = False
                                                break
                        else:
                                for key, value in self.specs.iteritems():
                                        if value[0] == deviceName:
                                                self.deviceName = value[0]
                                                self.basePath = os.path.join("/sys/bus/usb/drivers/usbhspec/", value[1])
                                                devNotFound = False
                                                break
                                        if key == deviceName:
                                                self.deviceName = value[0]
                                                self.basePath = os.path.join("/sys/bus/usb/drivers/usbhspec/", value[1])
                                                devNotFound = False
                                                break

        if devNotFound == True:
                print("Device %s not found! Exiting ..." % (deviceName))
                sys.exit()

        if self.usedInterface == 'kernel':
                #: First calibration coefficient of the spectrometer. Pixel counting starts at 1!
                self.startWavelength = float(file(os.path.join(self.basePath,"a0")).read())
                #: Second calibration coefficient.
                self.firstKoeff      = float(file(os.path.join(self.basePath,"a1")).read())
                #: Third calibration coefficient.
                self.secondKoeff     = float(file(os.path.join(self.basePath,"a2")).read())
                #: Fourth calibration coefficient.
                self.thirdKoeff      = float(file(os.path.join(self.basePath,"a3")).read())
                #: Fifth calibration coefficient.
                self.fourthKoeff     = float(file(os.path.join(self.basePath,"a4")).read())
                #: Guess what!
                self.fifthKoeff      = float(file(os.path.join(self.basePath,"a5")).read())
                self.deviceName = file(os.path.join(self.basePath,"device_name")).read().strip()
                self.sensorName = file(os.path.join(self.basePath,"sensor_name")).read().strip()

                self.devicePath = "/dev/%s" % (self.deviceName)
        else: # self.usedInterface == 'pyusb'
                # we do know the serialNumber!

                value = self.specs[self.serialNumber]
                dev = value[3]

                # create endpoints

                cfg = dev.get_active_configuration()
                interface_number = cfg[(0,0)].bInterfaceNumber
                alternate_setting = usb.control.get_interface(dev, interface_number)
                intf = usb.util.find_descriptor(cfg, bInterfaceNumber = interface_number,bAlternateSetting = alternate_setting)

                self.ep1Out = usb.util.find_descriptor(intf, custom_match = lambda e: e.bEndpointAddress == 0x01)
                self.ep1In  = usb.util.find_descriptor(intf, custom_match = lambda e: e.bEndpointAddress == 0x81)
                self.ep2    = usb.util.find_descriptor(intf, custom_match = lambda e: e.bEndpointAddress == 0x82)
                self.ep6    = usb.util.find_descriptor(intf, custom_match = lambda e: e.bEndpointAddress == 0x86)

                #: Get start wavelength
                self.startWavelength = self._query(0x01, "num")
                #: Second calibration coefficient.
                self.firstKoeff      = self._query(0x02, "num")
                #: Third calibration coefficient.
                self.secondKoeff     = self._query(0x03, "num")
                #: Fourth calibration coefficient.
                self.thirdKoeff      = self._query(0x04, "num")
                #: Fifth calibration coefficient.
                self.fourthKoeff     = 0.0
                #: Guess what!
                self.fifthKoeff      = 0.0
                self.sensorName = ''

                self.deviceName = dev


        # Default
        self.pixelOffset = 0
        # S10420-1006/-1106 CCD image sensor see documentation (Device structure)
        if (self.sensorName == "S10420-1106") or (self.sensorName == "S10420-1006"):
                self.pixelOffset = 10
                print ("Sensor '%s' means pixel offset of %d" % (self.sensorName, self.pixelOffset))
        elif (self.sensorName.find("S8377") > -1) or (self.sensorName.find("S8378") > -1):
                self.pixelOffset = 0
                print ("Sensor '%s' means pixel offset of %d" % (self.sensorName, self.pixelOffset))



        # gereate wavelength array
        self.wlArr = np.zeros(PIXEL_COUNT_USB4000)
        for pix in range(PIXEL_COUNT_USB4000):
                self.wlArr[pix] = self.startWavelength       + \
                                   pix *   self.firstKoeff   + \
                                  (pix**2)*self.secondKoeff  + \
                                  (pix**3)*self.thirdKoeff   + \
                                  (pix**4)*self.fourthKoeff  + \
                                  (pix**5)*self.fifthKoeff
        print self.wlArr

    def findAllConnectedSpectrometers(self):
            return self.specs
    def _findAllConnectedSpectrometers(self):
        """Function to find all connected USB-spectrometers

        Returns a list/dictionary? with spectrometers containing:
        - device name
        - serial number
        - start wavelength
        """

        specs = {}
        self.usedInterface = "kernel"

        basePath = "/sys/bus/usb/drivers/usbhspec/"
        if not os.path.exists(basePath):
                self.usedInterface = "pyusb"
                print ("No spectrometer found using the kernel module.")
                print ("Now testing pyusb!")

        if self.usedInterface == "kernel":
                fList = os.listdir(basePath)

                for i in fList:
                        mtch = re.search("\d\-\d.*\:\d+\.\d+", i)
                        if mtch:
                                serNr = open(os.path.join(basePath, i, "serial_number"), "r").read().strip()
                                res = getDeviceFileFromAddress("usb", i)
                                if len(res) != 1:
                                        print("Something went wrong. I found two USB devices with the same path!")
                                        for i in res:
                                                print (i)
                                        print("PLEASE call someone (Carsten) who knows what to do now!")
                                        sys.exit()

                                specs[serNr] = (res[0][0], i, "%.0f" % (float(file(os.path.join(basePath, i,"a0")).read())))
        elif self.usedInterface == "pyusb":
                # use the pyusb interface (only ONE of these interfaces WILL work)
                devs = usb.core.find(idVendor=USB_USBSPEC_VENDOR_ID, idProduct=USB_USBSPEC_PRODUCT_ID_USB4000, find_all=True)
                #devs = usb.core.find(idVendor=USB_USBSPEC_VENDOR_ID, idProduct=USB_USBSPEC_PRODUCT_ID_USB650, find_all=True)

                if len(devs) > 0:
                        print "Found %d spectrometer(s) via pyusb!" % (len(devs))
                else:
                        print "Also no spectrometer found using pyusb."

                # find alls connected devices
                for dev in devs:
                        #dev.set_configuration()
                        #cfg = dev.get_active_configuration()
                        #interface_number = cfg[(0,0)].bInterfaceNumber
                        #alternate_setting = usb.control.get_interface(dev, interface_number)
                        #intf = usb.util.find_descriptor(cfg, bInterfaceNumber = interface_number,bAlternateSetting = alternate_setting)

                        cfg=dev[0]
                        intf=cfg[(0, 0)]

                        self.ep1Out=intf[0]
                        self.ep1In =intf[3]

                        #self.ep1Out = usb.util.find_descriptor(intf, custom_match = lambda e: e.bEndpointAddress == 0x01)
                        #self.ep1In  = usb.util.find_descriptor(intf, custom_match = lambda e: e.bEndpointAddress == 0x81)

                        readSuccess = False
                        while not readSuccess:
                                # INITIALIZE
                                self.ep1Out.write(chr(0x01))
                                time.sleep(0.5)
                                readSuccess = True
                                # get integration time

                                #self.ep1Out.write(chr(0xfe))
                                #try:
                                        #res = self.ep1In.read(64)
                                        #readSuccess = True
                                #except usb.core.USBError:
                                        #print "Failed"
                                        #pass

                        #int_time = (res[5]<<24)+(res[4]<<16)+(res[3]<<8)+res[2]
                        #print int_time

                        # get necessary data for all devices {'510C2114': ('usbhspec0', '5-2:1.0', '324'  )}
                        #                                    { serialNo : ( 'pyusb'   ,  None    , firstWL)}
                        # get serial number
                        serNr = self._query(0x00, "str")
                        # get a0
                        a0 = self._query(0x01, "num")
                        del(self.ep1Out, self.ep1In)
                        specs[serNr] = ( 'pyusb'   ,  None    ,  "%.0f" % (float(a0)), dev)
        else:
                print "This point should never be reached!"
                sys.exit()

        if len(specs) == 0:
                self.usedInterface = None

        return specs

    def _query(self, byte, decode=None):
        self.ep1Out.write(chr(0x05) + chr(byte))
        res = self.ep1In.read(64)
        if   decode == 'str':
            s   = ''.join(map(chr,res[2:])).rstrip()
            res = s.replace('\x00','')
            res = res.replace('\xa4','')
        elif decode == 'num':
            s   = ''.join(map(chr,res[2:])).rstrip()
            res = s.replace('\x00','')
            res = res.replace('\xa4','')  #FIXME: ??
            res = float(res)
        return res

    def setIntegrationTime(self, intTime, test=True):
        # integration_time possible values between 10 - 65535000 (in usec)
        if (intTime < 10) or  (intTime > 65535000):
                print "USB4000.setIntegrationTime : Integration Time not allowed! please use vaues between"
                print "10 and 65535000 µs"
                return False
        while True:
                if   self.usedInterface == 'pyusb':
                        c = []
                        c.append( intTime        & 0xFF )
                        c.append((intTime >>  8) & 0xFF )
                        c.append((intTime >> 16) & 0xFF )
                        c.append((intTime >> 24) & 0xFF )
                        self.ep1Out.write(chr(0x02) + bytearray(c))
                else:
                        print ("Interface not yet implemented")
                        sys.exit()

                if not test:
                        break
                time.sleep(.01)
                devIT = self.getIntegrationTime()
                print ("setIntTime : %d  ----  deviceIntTime : %d" % (devIT, intTime))
                if devIT == intTime:
                        break
                if (time.time() - startT) > 1.0:
                        return False
        self.integrationTime = intTime
        return True

    def getIntegrationTime(self):
        # integration_time possible values between 10000 and 10000000 (in usec)
        if   self.usedInterface == 'pyusb':

                startT = time.time()
                self.ep1Out.write(chr(0xfe))
                res    = self.ep1In.read(64)
                #while len(res) <> 4:
                        #print("--------------------------------- getIntegrationTime -- Answer incorrect (too long or too short)!")
                        #time.sleep(.01)
                        #res    = self.deviceName.ctrl_transfer(bmRequestType = 0xc0, bRequest = 0x0b, wValue = 0x01, wIndex = 0x00, data_or_wLength = 4, timeout = 2000)
                        #if (time.time() - startT) > .5:
                                #raise
                intTime = (res[5] << 24) + (res[4] << 16) + (res[3] << 8) + res[2]
        elif self.usedInterface == 'kernel':
                print ("Interface not yet implemented")
                sys.exit()
        return intTime

    def getSensorName(self):
        return self.sensorName

    def getSerialNumber(self):
        return self.serialNumber

    def getSpectrum(self, timeout = None):
        """This function grabs spectral data from the spectrometer. Addidtional
        information is also encoded in the data read from the interface so
        take nothing for granted!

        I've got two different spectrometers from which I tried to conclude
        what to do with the data. I may have made invalid assumptions!

        You have to read 0x1040 bytes of data. These are 16bit numbers so it does
        make sense to calculate these numbers from the data and the only use those
        integers.

        The first number (16 bit in this context) was alwas 2. That only changes
        if you read data if the spectrometer is not yet ready (integration time).
        If the spectrometer isn't ready all numers are zero.

        The second number is an index which is 0,1 or 2 and just counts up.

        Third is the amount of active pixels (in contrast to the amount of pixels
        sixth number (index 5)). Please see the documentation to your image sensor
        (e.g. S10420-1106 from Hamamtsu).

        Forth (index 3) is the most important number because it says where to find
        the first pixel in the whole dataset of 0x1040/2 = 0x820 16bit numbers.

        The fifth seems to be the end index because startIndex + amountOfPixels = endIndex
        HOWEVER in my case the end index is higer than 0x820 which means that I can be
        very wrong with my interpretation.

        In my case and using the S10420-1106 sensor I found that the first four numbers
        of the spectrum (starting with startIndex) seem to be darkened pixels. You can
        increase the integration time as much as you wish these numbers stay (more or less)
        the same. Use at your own risc!

        Actually the spectrum seems to start at startIndex + 10 pixels/numbers which was
        veryfied for MY spectrometer with a really good and freshly checked laboratory
        spectrometer from Perkin Elmer (wavelength correctness was checkt with the aid of
        special filters).
        So I calculate the start of the spectrum unsing
        startSpectrum = startIndex + (amountOfPixels - amountOfActivePixels) / 2
        which seems to make sense.

        The wavelength correctness was VERY good compared to spectrometers from avantes,
        ocean optics and trios. We estimat an offset of about .4 nm over the whole spectrum
        which lies in the tolerance of of our measurement setup.
        """

        if timeout == None:
                timeout = self.integrationTime / 1000000.0 * 2.1
        startT = time.time()
        while 1:
                #: Grab data from the interface
                if self.usedInterface == 'pyusb':
                        # ask for the data
                        self.ep1Out.write(chr(0x09))
                        resArr = np.zeros(256 * 15)
                        resArrIndex = 0
                        # read four times from endpoint 6 an four times from ep2
                        while 1:
                                try:
                                        res = self.ep6.read(512)
                                except usb.core.USBError:
                                        if (time.time() - startT) > timeout:
                                                raise usb.core.USBError("Timeout")
                                        time.sleep(.01)
                                        continue
                                else:
                                        break

                        for i in range(0,len(res),2):
                                resArr[resArrIndex] = (res[i+1] << 8) + res[i]
                                resArrIndex += 1


                        for i in range(3):
                            res = self.ep6.read(512)
                            for i in range(0,len(res),2):
                                resArr[resArrIndex] = (res[i+1] << 8) + res[i]
                                resArrIndex += 1
                        for i in range(4,15):
                            res = self.ep2.read(512)
                            for i in range(0,len(res),2):
                                resArr[resArrIndex] = (res[i+1] << 8) + res[i]
                                resArrIndex += 1
                        sync_packet = self.ep2.read(1)
                        return resArr
                else:
                        return None

        return resArr





def frange(start, end=None, inc=None):
    "A range function, that does accept float increments..."

    if end == None:
        end = start + 0.0
        start = 0.0

    if inc == None:
        inc = 1.0

    L = []
    while 1:
        next = start + len(L) * inc
        if inc > 0 and next >= end:
            break
        elif inc < 0 and next <= end:
            break
        L.append(next)

    return L

if __name__ == '__main__':

        def mean(data):
                return sum(data)/float(len(data))





        ham = USB4000()

        print ham.findAllConnectedSpectrometers()

        ham.setIntegrationTime(10000000)
        res = ham.getSpectrum()
        print res

        #sys.exit()
