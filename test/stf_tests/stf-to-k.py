# Taken from https://github.com/p4lang/p4c/blob/master/backends/bmv2/bmv2stf.py

#!/usr/bin/env python
# Copyright 2013-present Barefoot Networks, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Runs the BMv2 behavioral model simulator with input from an stf file

from __future__ import print_function
from subprocess import Popen
from threading import Thread
from glob import glob
import json
import sys
import re
import os
import stat
import tempfile
import shutil
import difflib
import subprocess
import signal
import time
import random
import errno
import socket
import math
from string import maketrans
from collections import OrderedDict
try:
    from scapy.layers.all import *
    from scapy.utils import *
except ImportError:
    pass

SUCCESS = 0
FAILURE = 1


table_info = {}
in_packets = []
out_packets = []

def makeVal(num, w=0):
    #if w == 0:
    #    w = math.ceil(math.log(num,2))
    return "@val(%d,%d,false)" % (num, w)

class TimeoutException(Exception): pass
def signal_handler(signum, frame):
    raise TimeoutException, "Timed out!"
signal.signal(signal.SIGALRM, signal_handler)

class Options(object):
    def __init__(self):
        self.binary = None
        self.verbose = False
        self.preserveTmp = False
        self.observationLog = None

def nextWord(text, sep = None):
    # Split a text at the indicated separator.
    # Note that the separator can be a string.
    # Separator is discarded.
    spl = text.split(sep, 1)
    if len(spl) == 0:
        return '', ''
    elif len(spl) == 1:
        return spl[0].strip(), ''
    else:
        return spl[0].strip(), spl[1].strip()

def ByteToHex(byteStr):
    return ''.join( [ "%02X " % ord( x ) for x in byteStr ] ).strip()

def HexToByte(hexStr):
    bytes = []
    hexStr = ''.join( hexStr.split(" ") )
    for i in range(0, len(hexStr), 2):
        bytes.append( chr( int (hexStr[i:i+2], 16 ) ) )
    return ''.join( bytes )

def reportError(*message):
    print("***", *message)

class Local(object):
    # object to hold local vars accessable to nested functions
    pass

def FindExe(dirname, exe):
    dir = os.getcwd()
    while len(dir) > 1:
        if os.path.isdir(os.path.join(dir, dirname)):
            rv = None
            rv_time = 0
            for dName, sdName, fList in os.walk(os.path.join(dir, dirname)):
                if exe in fList:
                    n=os.path.join(dName, exe)
                    if os.path.isfile(n) and os.access(n, os.X_OK):
                        n_time = os.path.getmtime(n)
                        if n_time > rv_time:
                            rv = n
                            rv_time = n_time
            if rv is not None:
                return rv
        dir = os.path.dirname(dir)
    return exe

def run_timeout(options, args, timeout, stderr):
    if options.verbose:
        print("Executing ", " ".join(args))
    local = Local()
    local.process = None
    def target():
        procstderr = None
        if stderr is not None:
            procstderr = open(stderr, "w")
        local.process = Popen(args, stderr=procstderr)
        local.process.wait()
    thread = Thread(target=target)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        print("Timeout ", " ".join(args), file=sys.stderr)
        local.process.terminate()
        thread.join()
    if local.process is None:
        # never even started
        reportError("Process failed to start")
        return -1
    if options.verbose:
        print("Exit code ", local.process.returncode)
    return local.process.returncode

timeout = 10 * 60

class ConcurrentInteger(object):
    # Generates exclusive integers in a range 0-max
    # in a way which is safe across multiple processes.
    # It uses a simple form of locking using folder names.
    # This is necessary because this script may be invoked
    # concurrently many times by make, and we need the many simulator instances
    # to use different port numbers.
    def __init__(self, folder, max):
        self.folder = folder
        self.max = max
    def lockName(self, value):
        return "lock_" + str(value)
    def release(self, value):
        os.rmdir(self.lockName(value))
    def generate(self):
        # try 10 times
        for i in range(0, 10):
            index = random.randint(0, self.max)
            file = self.lockName(index)
            try:
                os.makedirs(file)
                return index
            except:
                time.sleep(1)
                continue
        return None

class BMV2ActionArg(object):
    def __init__(self, name, width):
        # assert isinstance(name, str)
        # assert isinstance(width, int)
        self.name = name
        self.width = width

class TableKey(object):
    def __init__(self):
        self.fields = OrderedDict()
    def append(self, name, type):
        self.fields[name] = type

class TableKeyInstance(object):
    def __init__(self, tableKey):
        assert isinstance(tableKey, TableKey)
        self.values = {}
        self.key = tableKey
        for f,t in tableKey.fields.iteritems():
            if t == "ternary":
                #self.values[f] = "0&&&0"
                self.values[f] = "$pair(@val(0,0,false),@val(0,0,false))"
            elif t == "lpm":
                #self.values[f] = "0/0"
                self.values[f] = "$pair(@val(0,0,false),@val(0,0,false))"
            elif t == "exact":
                #self.values[f] = "0"
                self.values[f] = "@val(0,0,false)"
            elif t == "valid":
                #self.values[f] = "0"
                self.values[f] = "@val(0,0,false)"
            else:
                raise Exception("Unexpected key type " + t)
    def set(self, key, value):
        array = re.compile("(.*)\$([0-9]+)(.*)");
        m = array.match(key)
        if m:
            key = m.group(1) + "[" + m.group(2) + "]" + m.group(3)

        found = False
        if key in self.key.fields:
            found = True
        elif key + '$' in self.key.fields:
            key = key + '$'
            found = True
        elif key + '.$valid$' in self.key.fields:
            key = key + '.$valid$'
            found = True
        elif key.endswith(".valid"):
            alt = key[:-5] + "$valid$"
            if alt in self.key.fields:
                key = alt
                found = True
        if not found:
            for i in self.key.fields:
                if i.endswith("." + key) or i.endswith("." + key + "$"):
                    key = i
                    found = True
                elif key == "valid" and i.endswith(".$valid$"):
                    key = i
                    found = True
        if not found and key == "valid" and "$valid$" in self.key.fields:
            key = "$valid$"
            found = True
        if not found:
            raise Exception("Unexpected key field " + key)
        if self.key.fields[key] == "ternary":
            self.values[key] = self.makeMask(value)
        elif self.key.fields[key] == "lpm":
            self.values[key] = self.makeLpm(value)
        elif self.key.fields[key] == "valid":
            self.values[key] = str(value)
        else:
            self.values[key] = makeVal(int(value, 0))
    def makeMask(self, value):
        # TODO -- we really need to know the size of the key to make the mask properly,
        # but to find that, we need to parse the headers and header_types from the json
        if value.startswith("0x"):
            mask = "F"
            value = value[2:]
            prefix = "0x"
            bits_per_digit = 4
        elif value.startswith("0b"):
            mask = "1"
            value = value[2:]
            prefix = "0b"
            bits_per_digit = 1
        elif value.startswith("0o"):
            mask = "7"
            value = value[2:]
            prefix = "0o"
            bits_per_digit = 3
        else:
            raise Exception("Decimal value "+value+" not supported for ternary key")
            return value
        values = "0123456789abcdefABCDEF*"
        replacements = (mask * 22) + "0"
        trans = maketrans(values, replacements)
        m = value.translate(trans)

        w = len(value) * bits_per_digit
        d = int(prefix + value.replace("*", "0"), 0)
        m = int(prefix + m, 0)
        return "$pair(%s,%s)" % (makeVal(d,w), makeVal(m,w))
        #return prefix + value.replace("*", "0") + "&&&" + prefix + m
    def makeLpm(self, value):
        if value.find('/') >= 0:
            return value
        if value.startswith("0x"):
            bits_per_digit = 4
        elif value.startswith("0b"):
            bits_per_digit = 1
        elif value.startswith("0o"):
            bits_per_digit = 3
        else:
            value = "0x" + hex(int(value))
            bits_per_digit = 4
        alldigits = len(value) - 2
        digits = len(value) - 2 - value.count('*')
        w = alldigits*bits_per_digit
        d = int(value.replace('*', '0'), 0)
        m = int("0b" + "1" * digits + "0" * (alldigits - digits), 0)
        #return value.replace('*', '0') + "/" + str(digits*bits_per_digit)
        return "$pair(%s,%s)" % (makeVal(d,w), makeVal(m,w))
    def __str__(self):
        # result = ""
        # for f in self.key.fields:
        #     if result != "":
        #         result += " "
        #     result += self.values[f]
        # return result
        return " ".join(["ListItem(%s)" % self.values[f] for f in self.key.fields])

class BMV2ActionArguments(object):
    def __init__(self, action):
        assert isinstance(action, BMV2Action)
        self.action = action
        self.values = {}
    def set(self, key, value):
        found = False
        for i in self.action.args:
            if key == i.name:
                found = True
        if not found:
            raise Exception("Unexpected action arg " + key)
        self.values[key] = value
    def __str__(self):
        # result = ""
        # for f in self.action.args:
        #     if result != "":
        #         result += " "
        #     result += self.values[f.name]
        #return result
        #print(result)
        if self.size() == 0:
            return ".List"
        return " ".join(["ListItem(@val(%d,0,false))" % int(self.values[f.name], 0) for f in self.action.args])
    def size(self):
        return len(self.action.args)

class BMV2Action(object):
    def __init__(self, jsonAction):
        self.name = jsonAction["name"]
        self.args = []
        for a in jsonAction["runtime_data"]:
            arg = BMV2ActionArg(a["name"], a["bitwidth"])
            self.args.append(arg)
    def __str__(self):
        return self.name
    def makeArgsInstance(self):
        return BMV2ActionArguments(self)

class BMV2Table(object):
    def __init__(self, jsonTable):
        self.match_type = jsonTable["match_type"]
        self.name = jsonTable["name"]
        self.key = TableKey()
        self.actions = {}
        for k in jsonTable["key"]:
            name = k["target"]
            if isinstance(name, list):
                name = ""
                for t in k["target"]:
                    if name != "":
                        name += "."
                    name += t
            self.key.append(name, k["match_type"])
        actions = jsonTable["actions"]
        action_ids = jsonTable["action_ids"]
        for i in range(0, len(actions)):
            actionName = actions[i]
            actionId = action_ids[i]
            self.actions[actionName] = actionId
    def __str__(self):
        return self.name
    def makeKeyInstance(self):
        return TableKeyInstance(self.key)

# Represents enough about the program executed to be
# able to invoke the BMV2 simulator, create a CLI file
# and test packets in pcap files.
class RunBMV2(object):
    def __init__(self, folder, options, jsonfile):
        self.uniqid = 0
        self.clifile = folder + "/cli.txt"
        self.jsonfile = jsonfile
        self.stffile = None
        self.folder = folder
        self.pcapPrefix = "pcap"
        self.interfaces = {}
        self.expected = {}
        self.packetDelay = 0
        self.options = options
        self.json = None
        self.tables = []
        self.actions = []
        self.switchLogFile = "switch.log"  # .txt is added by BMv2
        self.readJson()
    def readJson(self):
        with open(self.jsonfile) as jf:
            self.json = json.load(jf)
        for a in self.json["actions"]:
            self.actions.append(BMV2Action(a))
        for t in self.json["pipelines"][0]["tables"]:
            self.tables.append(BMV2Table(t))
        for t in self.json["pipelines"][1]["tables"]:
            self.tables.append(BMV2Table(t))
    def filename(self, interface, direction):
        return self.folder + "/" + self.pcapPrefix + str(interface) + "_" + direction + ".pcap"
    def interface_of_filename(self, f):
        return int(os.path.basename(f).rstrip('.pcap').lstrip(self.pcapPrefix).rsplit('_', 1)[0])
    def do_cli_command(self, cmd):
        print(cmd)
        # if self.options.verbose:
        #     print(cmd)
        # self.cli_stdin.write(cmd + "\n")
        # self.cli_stdin.flush()
        # self.packetDelay = 1
    def do_command(self, cmd):
        if self.options.verbose:
            print("STF Command:", cmd)
        first, cmd = nextWord(cmd)
        if first == "":
            pass
        elif first == "add":
            self.do_cli_command(self.parse_table_add(cmd))
        elif first == "setdefault":
            self.do_cli_command(self.parse_table_set_default(cmd))
        elif first == "packet":
            interface, data = nextWord(cmd)
            interface = int(interface)
            data = ''.join(data.split())
            bindata = ''.join(["{:04b}".format(int(i,16)) for i in data])
            in_packets.append("ListItem($packet(\"%s\",%d))" % (bindata, interface))
            print(data)
            #time.sleep(self.packetDelay)
            # try:
            #     self.interfaces[interface]._write_packet(HexToByte(data))
            # except ValueError:
            #     reportError("Invalid packet data", data)
            #     return FAILURE
            # self.interfaces[interface].flush()
            self.packetDelay = 0
        elif first == "expect":
            interface, data = nextWord(cmd)
            interface = int(interface)
            data = ''.join(data.split())
            if data != '':
                bindata = ''.join(["{:04b}".format(int(i,16)) if i != '*' else '****' for i in data])
                out_packets.append("%s %d" % (bindata, interface))
                print("e%s" % data)
            #     self.expected.setdefault(interface, []).append(data)
        else:
            if self.options.verbose:
                print("ignoring stf command:", first, cmd)
    def parse_table_set_default(self, cmd):
        tableName, cmd = nextWord(cmd)
        table = self.tableByName(tableName)
        actionName, cmd = nextWord(cmd, "(")
        action = self.actionByName(table, actionName)
        actionArgs = action.makeArgsInstance()
        cmd = cmd.strip(")")
        while cmd != "":
            word, cmd = nextWord(cmd, ",")
            k, v = nextWord(word, ":")
            actionArgs.set(k, v)

        if tableName not in table_info:
            table_info[tableName] = {"entry": []}

        table_info[tableName]["default"] = ("""
            @call(
              String2Id("%s"),
              $resolved(
                %s
              )
            )
        """ % (actionName,str(actionArgs)))
        command = "table_set_default " + tableName + " " + actionName
        if actionArgs.size():
            command += " => " + str(actionArgs)
        return command
    def parse_table_add(self, cmd):
        tableName, cmd = nextWord(cmd)
        table = self.tableByName(tableName)
        key = table.makeKeyInstance()
        actionArgs = None
        actionName = None
        prio, cmd = nextWord(cmd)
        number = re.compile("[0-9]+")
        if not number.match(prio):
            # not a priority; push back
            cmd = prio + " " + cmd
            prio = ""
        while cmd != "":
            if actionName != None:
                # parsing action arguments
                word, cmd = nextWord(cmd, ",")
                k, v = nextWord(word, ":")
                actionArgs.set(k, v)
            else:
                # parsing table key
                word, cmd = nextWord(cmd)
                if word.find("(") >= 0:
                    # found action
                    actionName, arg = nextWord(word, "(")
                    action = self.actionByName(table, actionName)
                    actionArgs = action.makeArgsInstance()
                    cmd = arg + cmd
                    cmd = cmd.strip("()")
                else:
                    k, v = nextWord(word, ":")
                    key.set(k, v)
        # if prio != "":
        #     # Priorities in BMV2 seem to be reversed with respect to the stf file
        #     # Hopefully 10000 is large enough
        #     prio = str(10000 - int(prio))
        if tableName not in table_info:
            table_info[tableName] = {"entry": []}
        if prio != "":
            prio = 10000 - int(prio)
        else:
            prio = 0
        entry = """
        ListItem($rule(%d,
                    $ctr(
                        %s
                    ),
                    @call(
                      String2Id("%s"),
                      $resolved(
                        %s
                      )
                    )
                 ))
        """ % (self.uniqid,str(key),actionName,str(actionArgs))
        table_info[tableName]["entry"].append((prio,self.uniqid,entry,entry))
        self.uniqid += 1
        command = "table_add " + tableName + " " + actionName + " " + str(key) + " => " + str(actionArgs)
        if table.match_type == "ternary":
            command += " " + str(prio)
        return command
    def actionByName(self, table, actionName):
        id = table.actions[actionName]
        action = self.actions[id]
        return action
    def tableByName(self, tableName):
        for t in self.tables:
            if t.name == tableName:
                return t
        raise Exception("Could not find table " + tableName)
    def interfaceArgs(self):
        # return list of interface names suitable for bmv2
        result = []
        for interface in sorted(self.interfaces):
            result.append("-i " + str(interface) + "@" + self.pcapPrefix + str(interface))
        return result
    def generate_model_inputs(self, stffile):
        self.stffile = stffile
        with open(stffile) as i:
            for line in i:
                line, comment = nextWord(line, "#")
                first, cmd = nextWord(line)
                if first == "packet" or first == "expect":
                    interface, cmd = nextWord(cmd)
                    interface = int(interface)
                    if not interface in self.interfaces:
                        # Can't open the interfaces yet, as that would block
                        ifname = self.interfaces[interface] = self.filename(interface, "in")
                        os.mkfifo(ifname)
        return SUCCESS
    def check_switch_server_ready(self, proc, thriftPort):
        """While the process is running, we check if the Thrift server has been
        started. If the Thrift server is ready, we assume that the switch was
        started successfully. This is only reliable if the Thrift server is
        started at the end of the init process"""
        while True:
            if proc.poll() is not None:
                return False
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(("localhost", thriftPort))
            if result == 0:
                return  True
    def run(self):
        # if self.options.verbose:
        #     print("Running model")
        # wait = 0  # Time to wait before model starts running
        #
        # concurrent = ConcurrentInteger(os.getcwd(), 1000)
        # rand = concurrent.generate()
        # if rand is None:
        #     reportError("Could not find a free port for Thrift")
        #     return FAILURE
        # thriftPort = str(9090 + rand)
        # rv = SUCCESS
        # try:
        #     os.remove("/tmp/bmv2-%d-notifications.ipc" % rand)
        # except OSError:
        #     pass
        # try:
        #     runswitch = [FindExe("behavioral-model", "simple_switch"),
        #                  "--log-file", self.switchLogFile, "--log-flush",
        #                  "--use-files", str(wait), "--thrift-port", thriftPort,
        #                  "--device-id", str(rand)] + self.interfaceArgs() + ["../" + self.jsonfile]
        #     if self.options.verbose:
        #         print("Running", " ".join(runswitch))
        #     sw = subprocess.Popen(runswitch, cwd=self.folder)
        #
        #     def openInterface(ifname):
        #         fp = self.interfaces[interface] = RawPcapWriter(ifname, linktype=0)
        #         fp._write_header(None)
        #
        #     # Try to open input interfaces. Each time, we set a 2 second
        #     # timeout. If the timeout expires we check if the bmv2 process is
        #     # not running anymore. If it is, we check if we have exceeded the
        #     # one minute timeout (exceeding this timeout is very unlikely and
        #     # could mean the system is very slow for some reason). If one of the
        #     # 2 conditions above is met, the test is considered a FAILURE.
        #     start = time.time()
        #     sw_timeout = 60
        #     # open input interfaces
        #     # DANGER -- it is critical that we open these fifos in the same
        #     # order as bmv2, as otherwise we'll deadlock.  Would be nice if we
        #     # could open nonblocking.
        #     for interface in sorted(self.interfaces):
        #         ifname = self.interfaces[interface]
        #         while True:
        #             try:
        #                 signal.alarm(2)
        #                 openInterface(ifname)
        #                 signal.alarm(0)
        #             except TimeoutException:
        #                 if time.time() - start > sw_timeout:
        #                     return FAILURE
        #                 if sw.poll() is not None:
        #                     return FAILURE
        #             else:
        #                 break
        #
        #     # at this point we wait until the Thrift server is ready
        #     # also useful if there are no interfaces
        #     try:
        #         signal.alarm(int(sw_timeout + start - time.time()))
        #         self.check_switch_server_ready(sw, int(thriftPort))
        #         signal.alarm(0)
        #     except TimeoutException:
        #         return FAILURE
        #     time.sleep(0.1)
        #
        #     runcli = [FindExe("behavioral-model", "simple_switch_CLI"), "--thrift-port", thriftPort]
        #     if self.options.verbose:
        #         print("Running", " ".join(runcli))
        #     cli = subprocess.Popen(runcli, cwd=self.folder, stdin=subprocess.PIPE)
        #     self.cli_stdin = cli.stdin
        with open(self.stffile) as i:
            for line in i:
                line, comment = nextWord(line, "#")
                self.do_command(line)
        #     cli.stdin.close()
        #     for interface, fp in self.interfaces.iteritems():
        #         fp.close()
        #     # Give time to the model to execute
        #     time.sleep(2)
        #     cli.terminate()
        #     sw.terminate()
        #     sw.wait()
        #     # This only works on Unix: negative returncode is
        #     # minus the signal number that killed the process.
        #     if sw.returncode != 0 and sw.returncode != -15:  # 15 is SIGTERM
        #         reportError("simple_switch died with return code", sw.returncode);
        #         rv = FAILURE
        #     elif self.options.verbose:
        #         print("simple_switch exit code", sw.returncode)
        #     cli.wait()
        #     if cli.returncode != 0 and cli.returncode != -15:
        #         reportError("CLI process failed with exit code", cli.returncode)
        #         rv = FAILURE
        # finally:
        #     try:
        #         os.remove("/tmp/bmv2-%d-notifications.ipc" % rand)
        #     except OSError:
        #         pass
        #     concurrent.release(rand)
        # if self.options.verbose:
        #     print("Execution completed")
        # return rv
    def comparePacket(self, expected, received):
        received = ''.join(ByteToHex(str(received)).split()).upper()
        expected = ''.join(expected.split()).upper()
        if len(received) < len(expected):
            reportError("Received packet too short", len(received), "vs", len(expected))
            return FAILURE
        for i in range(0, len(expected)):
            if expected[i] == "*":
                continue;
            if expected[i] != received[i]:
                reportError("Packet different at position", i, ": expected", expected[i], ", received", received[i])
                return FAILURE
        return SUCCESS
    def showLog(self):
        with open(self.folder + "/" + self.switchLogFile + ".txt") as a:
            log = a.read()
            print("Log file:")
            print(log)
    def checkOutputs(self):
        if self.options.verbose:
            print("Comparing outputs")
        direction = "out"
        for file in glob(self.filename('*', direction)):
            interface = self.interface_of_filename(file)
            if os.stat(file).st_size == 0:
                packets = []
            else:
                try:
                    packets = rdpcap(file)
                except:
                    reportError("Corrupt pcap file", file)
                    self.showLog()
                    return FAILURE

            # Log packets.
            if self.options.observationLog:
                observationLog = open(self.options.observationLog, 'w')
                for pkt in packets:
                    observationLog.write('%d %s\n' % (
                        interface,
                        ''.join(ByteToHex(str(pkt)).split()).upper()))
                observationLog.close()

            # Check for expected packets.
            if interface not in self.expected:
                # This continue can falsely make a test succeed, if the
                # interface type is not the one stored in expected. We need to
                # be more careful on declaring success.
                #
                # One possible fix is to check for all expected and determine
                # which file to look into, or, remove the ones we found from the
                # self.expected list, and return success only if the list is
                # empty. The latter is what is implemented below.
                continue
            expected = self.expected[interface]
            if len(expected) != len(packets):
                reportError("Expected", len(expected), "packets on port", str(interface),
                            "got", len(packets))
                self.showLog()
                return FAILURE
            for i in range(0, len(expected)):
                cmp = self.comparePacket(expected[i], packets[i])
                if cmp != SUCCESS:
                    reportError("Packet", i, "on port", str(interface), "differs")
                    return FAILURE
            # remove successfully checked interfaces
            del self.expected[interface]
        if len(self.expected) != 0:
            # didn't find all the expects we were expecting
            reportError("Expected packects on ports", self.expected.keys(), "not received")
            return FAILURE
        else:
            return SUCCESS

def run_model(options, tmpdir, jsonfile, testfile):

    bmv2 = RunBMV2(tmpdir, options, jsonfile)
    result = bmv2.generate_model_inputs(testfile)
    if result != SUCCESS:
        return result
    result = bmv2.run()
    if result != SUCCESS:
        return result
    result = bmv2.checkOutputs()
    return result

######################### main

def usage(options):
    print("usage:", options.binary, "[-v] [-observation-log <file>] <json file> <stf file>");

def main(argv):
    options = Options()
    options.binary = argv[0]
    argv = argv[1:]
    while len(argv) > 0 and argv[0][0] == '-':
        if argv[0] == "-b":
            options.preserveTmp = True
        elif argv[0] == "-v":
            options.verbose = True
        elif argv[0] == '-observation-log':
            if len(argv) == 1:
                reportError("Missing argument", argv[0])
                usage(options)
                sys.exit(1)
            options.observationLog = argv[1]
            argv = argv[1:]
        else:
            reportError("Unknown option ", argv[0])
            usage(options)
        argv = argv[1:]
    if len(argv) < 2:
        usage(options)
        return FAILURE
    if not os.path.isfile(argv[0]) or not os.path.isfile(argv[1]):
        usage(options)
        return FAILURE

    tmpdir = tempfile.mkdtemp(dir=".")
    result = run_model(options, tmpdir, argv[0], argv[1])
    if options.preserveTmp:
        print("preserving", tmpdir)
    else:
        shutil.rmtree(tmpdir)
    if options.verbose:
        if result == SUCCESS:
            print("SUCCESS")
        else:
            print("FAILURE", result)

#=============================================================
    k = open(argv[2],'w')
    if len(table_info) > 0:
        k.write("""
<tables>
    ...
""")
    for t in table_info:
        table_info[t]["entry"] = sorted(table_info[t]["entry"])
        s = """
    <table>
        ...
        <name> %s </name>
        <rules> .List => %s </rules>
        <default> .K => %s </default>
    </table>
        """ % (t,
               "\n".join([x[2] for x in table_info[t]["entry"]]) if len(table_info[t]["entry"]) > 0 else ".List",
               table_info[t]["default"] if "default" in table_info[t] else ".K"
               )
        k.write(s)
    if len(table_info) > 0:
        k.write("""
</tables>
""")
    if len(in_packets) > 0:
        k.write("""
<in> .List =>
        %s
</in>
""" % "\n\t".join(in_packets))

    if len(table_info) > 0:
        k.write("""
syntax Id ::=
    %s
""" % ("\n\t|".join(["\"%s\" [token]" % t for t in table_info])))

    with open(argv[3], 'w') as f:
        f.write("\n".join(out_packets))

#=============================================================

    return result

if __name__ == "__main__":
    sys.exit(main(sys.argv))

