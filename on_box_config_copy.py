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
      - In this example, Ma1 is in a VRF.  If no VRF is used
        'sudo ip netns exec ns-<ma1_vrf>' can be removed.
      
           event-handler CONFIG-COPY
             trigger on-startup-config
             action bash python sudo ip netns exec ns-<ma1_vrf> python /mnt/flash/on_box_config_copy.py -d <dest_ip> -t <dest_type>
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
import sys
import syslog

# Set to allow unverified cert for eAPI call
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

# Setup timeout function and signal
import signal
def handler(signum, frame):
    syslog.syslog("%%ConfigCopy-6-LOG: Timed out waiting for destination eAPI.")
    raise Exception("timeout")

signal.signal(signal.SIGALRM, handler)
signal.alarm(5)

# ----------------------------------------------------------------
# Configuration section for Remote Location
# ----------------------------------------------------------------
username = 'admin'
password = 'arista'
# ----------------------------------------------------------------

def arg_it_up():
    """ Pulls in Args
        Returns:
            dest_ip (string): Destination IP for Copy
            dest_type (string): Type of Destination (Switch or Server)
    """
    # Pull in arguments to configure script logic
    parser = argparse.ArgumentParser(description='Save config to external location')
    required_arg = parser.add_argument_group('Required Arguments')
    required_arg.add_argument('-d', '--destination', dest='destination', required=True,
                              help='IP of Location to Copy to', type=str)
    required_arg.add_argument('-t', '--type', dest='type', required=True,
                              help='server or switch', type=str)
    args = parser.parse_args()
    dest_ip = args.destination
    dest_type = args.type
    return dest_ip, dest_type

def get_startup_config(switch):
    """ Copies startup-config as text via Unix Socket
        Arg:
            switch (instance): JSON-RPC instance for eAPI call to Switch
        Returns:
            startup_config (string): startup-config of local switch.
    """
    syslog.syslog("%%ConfigCopy-6-LOG: Copying startup-config...")
    startup_config = switch.runCmds(1, ["enable", "show startup-config"], "text")[1]["output"]
    startup_config = '\n'.join(startup_config.split('\n')[6:])
    return startup_config

def modify_config(config, ip, switch):
    """ Replaces Management IP and Hostname of Config for backup device
        Args:
            config (string): Unmodified startup config
            switch (instance): JSON-RPC instance for eAPI call to Switch
        Returns:
            modified_config (string): Modified config
    """
    syslog.syslog("%%ConfigCopy-6-LOG: Destination is remote switch. Modifying config hostname and Ma1 IP...")
    # Replace hostname with hostname-backup
    hostname = switch.runCmds(1, ["show hostname"])[0]["hostname"]
    temp_config = config.replace("hostname " + hostname, "hostname " + hostname + "-backup")
    # Replace Management1 IP with Destination Switch Management1 IP
    ma1_ip_int = switch.runCmds(1, ["show interfaces Management1"])
    ma1_ip = ma1_ip_int[0]["interfaces"]["Management1"]["interfaceAddress"][0]["primaryIp"]["address"]
    ma1_mask = str(ma1_ip_int[0]["interfaces"]["Management1"]["interfaceAddress"][0]["primaryIp"]["maskLen"])
    temp_config = temp_config.replace(ma1_ip + "/" + ma1_mask, ip + "/" + ma1_mask)
    # Remove Event-Handler Config to prevent some sort of infinite loop
    temp_config_list = temp_config.split("!\n")
    modified_config = ""
    for config_section in temp_config_list:
        if config_section.startswith("event-handler CONFIG-BACKUP"):
            continue
        elif config_section.startswith("end"):
            continue
        else:
            modified_config += config_section
    return modified_config

def dest_eapi_copy(ip, config):
    """ Sets up peer JSON-RPC instance based on Destination IP Arg
        and copies modified startup-config
        Args:
            ip (string): Destination IP of Remote Switch
            config (string): Modified startup-config
        Returns:
            config_response (list): Responses for each command
    """
    # Use Dest IP for peer switch eAPI connection
    syslog.syslog("%%ConfigCopy-6-LOG: Opening Destination eAPI Connection...")
    dest_url_string = "https://{}:{}@{}/command-api".format(username, password, ip)
    switch_req = Server(dest_url_string)
    # Split config by line and apply
    split_config = config.split("\n")
    commands = ["enable", "configure"] + split_config
    syslog.syslog("%%ConfigCopy-6-LOG: Pushing Configuration to Destination Switch...")
    config_response = switch_req.runCmds(1, commands)
    return config_response

def dest_server_copy(config):
    """ Copies un-modified startup-config to external SCP Server
        Args:
            config (string): Unmodified startup-config
    """
    # Use Dest IP for SCP destination

def main():
    # Pull in CLI Arguments
    cli_args = arg_it_up()
    copy_ip = cli_args[0]
    copy_type = cli_args[1]
    # Open syslog for log creation
    syslog.openlog('OnBoxConfigCopy', 0, syslog.LOG_LOCAL4)
    # Define URL for local eAPI connection. Uses Unix Socket
    local_switch = Server("unix:/var/run/command-api.sock")
    # Pull in startup-config
    main_start_config = get_startup_config(local_switch)
    if copy_type == "switch":
        backup_config = modify_config(main_start_config, copy_ip, local_switch)
        dest_eapi_copy(copy_ip, backup_config)
        syslog.syslog("%%ConfigCopy-6-LOG: Configuration Copy completed successfully...")
    elif copy_type == "server":
        syslog.syslog("%%ConfigCopy-6-LOG: Invalid Destination Type. Valid options are 'switch'...")
        syslog.syslog("%%ConfigCopy-6-LOG: Exiting script...")
        sys.exit()
    else:
        # Only allows for two options for now.  Exit on all other options.
        syslog.syslog("%%ConfigCopy-6-LOG: Invalid Destination Type. Valid options are 'server' or 'switch'...")
        syslog.syslog("%%ConfigCopy-6-LOG: Exiting script...")
        sys.exit()

if __name__ == "__main__":
    main()