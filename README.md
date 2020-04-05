# on_box_config_copy

This is a basic script to run on an Arista EOS device that will copy the running configuration to another location for archival purposes.  The initial version only allows for copying to another EOS spare device.

# Installation

In order to install this script:
- Copy the script to /mnt/flash.  For example, you can enable the root user temporarily on the main device for SCP.
```
aaa root secret <root_password>
```

- Then from your laptop:
```
scp on_box_config_copy.py root@<Management IP>:/mnt/flash
```

- Back on the EOS device, you can disable the root user.
```
no aaa root
```

- Enable the Command API interface and Unix Socket.  This config should be placed on both the source EOS device and the target EOS device to copy to.  Include Management VRF if in use:
```
management api http-commands
   protocol unix-socket
   no shutdown
   !
   vrf management
      no shutdown
```

# Usage
- Script should be configured to trigger with an Event Handler.

- The trigger action on-startup-config will execute the script any time the `wr mem` command is executed.

- The script uses passed arguments as indicated below.  Only type switch is supported today.

- The script assumes that the Management Mask and Gateway are the same for the source and destination EOS devices.

- Delay and Timeout can be tweaked per environment needs.

- The Event-Handler Config below assumes the use of a Management VRF.  The ip netns exec command can be removed if the default VRF is in use.
```
event-handler CONFIG-COPY
   trigger on-startup-config
   action bash sudo ip netns exec ns-<ma1_vrf> python /mnt/flash/on_box_config_copy.py -d <dest_ip> -t switch
   delay 5
   timeout 30
```

# Compatibility

This has been tested with EOS 4.23.2F using eAPI

# Limitations

For the initial version, copying is only allowed to another EOS device and connectivity must be through the Management1 interface.  Future versions will allow for more flexibility.
