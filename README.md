Welcome to the GitHub Community for the MDS Switch. PowerOn Auto Provisioning (POAP) is a CISCO provided feature which 
automates the process of upgrading software images and installing configuration files on devices that are being deployed in 
the network for the first time. The Python script can be used to automate day zero provisioning and upgrade process. 
For detailed developer documentation, please visit https://www.cisco.com/c/en/us/td/docs/dcn/mds9000/sw/9x/configuration/fundamentals/cisco-mds-9000-nx-os-fundamentals-configuration-guide-9x/using_poap.html

Understanding the script:

1. Checks for free space in the switch and if there is free space, the script downloads the kickstart and system images.
2. Verifies the integrity of the downloaded kickstart and sytem images using its md5 checksum. 
3. Gets the config file from the server.
4. Installs the images and then configures the switch using the downloaded config file. 

Paramters for the script:

The script (poap.py) has to be modified based on the requirements before moving forward with the day zero provisioning. 
The options dictionary stores all the paramters which can be tweaked to get the required results with the script.
(Only the options dictionary should be changed, rest of the script remains static). 
The available paramters in the options dictionary are:- 
"protocol"                  :-   The transfer protocol that is to be used to copy the files 
"username"                  :-   username that is to be used if the file server requires login
"ftp_username"              :-   username to be used for ftp
"password"                  :-   password that is to be if the file server required login
"hostname"                  :-   The hostname of the file server from which we want to copy files.
"target_system_image"       :-   The target system image that we want the switch to upgrade to.
"target_kickstart_image"    :-   The target kickstart image that we want the switch to upgrade to.

The script should work as expected once the parameters/options are configured. Please reach out to CISCO TAC if you have hit 
any issues. If the TAC team finds a bug, the fix will be integrated into the script. 
