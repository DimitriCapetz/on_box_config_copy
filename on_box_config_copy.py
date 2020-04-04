#!/usr/bin/python
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#  - Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#  - Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#  - Neither the name of Arista Networks nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL ARISTA NETWORKS
# BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
# BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN
# IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
#
#    Version 1.0 4/4/2020
#    Written by: 
#       Dimitri Capetz, Arista Networks
#
#    Revision history:
#       1.0 - Initial version tested on EOS 4.23.2F
"""
    DESCRIPTION
     The On-Box Config Copy script is meant to archive a copy of the
     running-config each time the config is saved (wr mem).  The script can 
     either archive using SCP without modification or can connect to a spare
     switch to install the config while modifying hostname and management IP.
   INSTALLATION
     In order to install this script:
       - Copy the script to /mnt/flash
       - Enable the Command API interface:
            management api http-commands
               protocol unix-socket
               no shutdown
       - Change username and password variables at the top of the script
         to the ones appropriate for your installation. 
   USAGE
      - Script should be configured to trigger with an Event Handlers.
      - The trigger action should be on the modification of startup-config.
      - The script uses passed arguments as indicated below.
      - Delay and threshold can be tweaked per environment needs.
      
           event-handler Downlink_Detect
             trigger on-intf <downlink> operstatus
             action bash python /mnt/flash/peer_interface_enabler.py -s <downlink> -v <vlan_list>
             delay 5
             timeout 30

   COMPATIBILITY
      This has been tested with EOS 4.23.2F using eAPI
   LIMITATIONS
      Currently assumes you are using the Ma1 Interface.
      Assumes destination management IP has same gateway and mask
"""

import argparse
from jsonrpclib import Server
import signal
import sys
import syslog

# Set to allow unverified cert for eAPI call
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# ----------------------------------------------------------------
# Configuration section for Remote Location
# ----------------------------------------------------------------
username = 'admin'
password = 'arista'
# ----------------------------------------------------------------

# Pull in arguments to configure script logic
parser = argparse.ArgumentParser(description='Save config to external location')
required_arg = parser.add_argument_group('Required Arguments')
required_arg.add_argument('-d', '--destination', dest='destination', required=True,
                          help='IP of Location to Copy to', type=str)
required_arg.add_argument('-t', '--type', dest='type', required=True,
                          help='Server or Switch', type=str)
args = parser.parse_args()
dest_ip = args.destination
dest_type = args.type

# Define URL for local eAPI connection. Uses Unix Socket
local_switch = Server("unix:/var/run/command-api.sock")

# Open syslog for log creation
syslog.openlog('OnBoxConfigCopy', 0, syslog.LOG_LOCAL4)

# Setup timeout function and signal
def handler(signum, frame):
    syslog.syslog("%%ConfigCopy-6-LOG: Timed out waiting for destination eAPI.")
    raise Exception("timeout")

signal.signal(signal.SIGALRM, handler)
signal.alarm(5)

def get_startup_config():
    """ Copies startup-config as text via Unix Socket
        Returns:
            startup_config (string): startup-config of local switch.
    """
    syslog.syslog("%%ConfigCopy-6-LOG: Copying startup-config...")
    startup_config = local_switch.runCmds(1, ["enable", "show startup-config"], "text")[1]["output"]
    return startup_config

def dest_eapi_copy(config):
    """ Sets up peer JSON-RPC instance based on Destination IP Arg
        and copies modified startup-config
        Args:
            config (string): Modified startup-config
        Returns:
            switch_req (instance): JSON-RPC instance for eAPI call to Dest
    """
    # Use Dest IP for peer switch eAPI connection
    syslog.syslog("%%ConfigCopy-6-LOG: Opening Peer eAPI Connection...")
    dest_url_string = "https://{}:{}@{}/command-api".format(username, password, dest_ip)
    switch_req = Server(peer_url_string)

    return switch_req

def dest_server_copy(config):
    """ Copies un-modified startup-config to external SCP Server
        Args:
            config (string): Unmodified startup-config
    """
    # Use Dest IP for SCP destination

def modify_config(config):
    """ Replaces Management IP and Hostname of Config for backup device
        Args:
            config (string): Unmodified startup config
        Returns:
            modified_config (string): Modified config
    """
    # Replace hostname with hostname-backup
    hostname = local_switch.runCmds(1, ["show hostname"])[0]["output"]["hostname"]
    temp_config_1 = config.replace("hostname " + hostname, "hostname " + hostname + "-backup")
    # Replace Management1 IP with Destination Switch Management1 IP
    ma1_ip_int = local_switch.runCmds(1, ["show interfaces Management1"])
    ma1_ip = ma1_ip_int[0]["output"]["interfaces"]["Management1"]["interfaceAddresses"][0]["primaryIp"]["address"]
    ma1_mask = str(ma1_ip_int[0]["output"]["interfaces"]["Management1"]["interfaceAddresses"][0]["primaryIp"]["maskLen"])
    modified_config = temp_config_1.replace(ma1_ip + "/" + ma1_mask, dest_ip + "/" + ma1_mask)
    return modified_config
