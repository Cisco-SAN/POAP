#!/bin/env python
#md5sum="a9515da3152f222815eca4e7b8a53700"
# Still needs to be implemented.
# Return Values:
# 0 : Reboot and reapply configuration
# 1 : No reboot, just apply configuration. Customers issue copy file run ; copy
# run start. Do not use scheduled-config since there is no reboot needed. i.e.
# no new image was downloaded
# -1 : Error case. This will cause POAP to restart the DHCP discovery phase. 

# The above is the (embedded) md5sum of this file taken without this line, 
# can be # created this way: 
# f=poap_ng.py ; cat $f | sed '/^#md5sum/d' > $f.md5 ; sed -i "s/^#md5sum=.*/#md5sum=\"$(md5sum $f.md5 | sed 's/ .*//')\"/" $f
# This way this script's integrity can be checked in case you do not trust
# tftp's ip checksum. This integrity check is done by /isan/bin/poap.bin).
# The integrity of the files downloaded later (images, config) is checked 
# by downloading the corresponding file with the .md5 extension and is
# done by this script itself.

import os
import re
import sys
import shutil
import signal
import string
import traceback
from cli import *
from time import gmtime, strftime

# **** Here are all variables that parametrize this script **** 
# *************************************************************

# system and kickstart images, configuration: location on server (src) and target (dst)
image_version       = "9.4.2"

# image_dir_src       = "/tftpboot"
# image_dir_src_root  = "/tftpboot" # part of path to remove during copy
image_dir_src = ""

target_system_image = "m9148v-s8ek9-mz.9.4.2.bin"          # Fill the target system image here
target_kickstart_image = "m9148v-s8ek9-kickstart-mz.9.4.2.bin"       # Fill the target kickstart image here

config_file_src     = "poap/poap.cfg" 
image_dir_dst       = "bootflash:poap"
system_image_dst        = "%s/system.img"      %  image_dir_dst
kickstart_image_dst     = "%s/kickstart.img"   %  image_dir_dst
config_file_dst     = "volatile:poap.cfg" # special copy command will copy to persistent location
md5sum_ext_src      = "md5" # extension of file containing md5sum of the one without ext.
# there is no md5sum_ext_dst because one the target it is a temp file
required_space = 250000 # Required space on /bootflash (for config and kick/system images)

#protocol="scp" # protocol to use to download images/config
protocol="tftp" # protocol to use to download images/config
# protocol="ftp" # protocol to use to download images/config
#protocol="sftp" # protocol to use to download images/config

# Host name and user credentials
username = "root" # tftp server account
ftp_username = "anonymous" # ftp server account
password = "nbv_12345"
hostname = "10.197.141.99"

# vrf info
vrf = "management"
if 'POAP_VRF' in os.environ:
    vrf=os.environ['POAP_VRF']

# Timeout info (from biggest to smallest image, should be f(image-size, protocol))
system_timeout    = 2100 
kickstart_timeout = 900  
config_timeout    = 120 
md5sum_timeout    = 120  

# POAP can use 3 modes to obtain the config file.
# - 'static' - filename is static
# - 'serial_number' - switch serial number is part of the filename
# - 'location' - CDP neighbor of interface on which DHCPDISCOVER arrived
#                is part of filename
# if serial-number is abc, then filename is $config_file_src.abc
# if cdp neighbor's device_id=abc and port_id=111, then filename is config_file_src.abc_111
# Note: the next line can be overwritten by command-line arg processing later
config_file_type = "static"
#config_file_type = "static"

# parameters passed through environment:
# TODO: use good old argv[] instead, using env is bad idea.
# pid is used for temp file name: just use getpid() instead!
# serial number should be gotten from "show version" or something!
pid=""
if 'POAP_PID' in os.environ:
    pid=os.environ['POAP_PID']
serial_number=None
if 'POAP_SERIAL' in os.environ:
    serial_number=os.environ['POAP_SERIAL']
cdp_interface=None
if 'POAP_INTF' in os.environ:
    cdp_interface=os.environ['POAP_INTF']

#Appending date and time to the logfile, so that logs are not overwritten. 
log_filename = "/bootflash/poap_%s.log" % (strftime("%Y%m%d%H%M%S", gmtime()))
t=time.localtime()
now="%d_%d_%d" % (t.tm_hour, t.tm_min, t.tm_sec)
#now=None
#now=1 # hardcode timestamp (easier while debugging)

# **** end of parameters **** 
# *************************************************************

# ***** argv parsing and online help (for test through cli) ******
# ****************************************************************

# poap.bin passes args (serial-number/cdp-interface) through env var
# for no seeminly good reason: we allow to overwrite those by passing
# argv, this is usufull when testing the script from vsh (even simple
# script have many cases to test, going through a reboto takes too long)

cl_cdp_interface=None  # Command Line version of cdp-interface
cl_serial_number=None  # can overwrite the corresp. env var
cl_protocol=None       # can overwride the script's default
cl_download_only=None  # dont write boot variables

def parse_args(argv, help=None):
    global cl_cdp_interface, cl_serial_number, cl_protocol, protocol, cl_download_only
    while argv:
        x = argv.pop(0)
        # not handling duplicate matches...
        if cmp('cdp-interface'[0:len(x)], x) == 0:
          try: cl_cdp_interface = argv.pop(0)
          except: 
             if help: cl_cdp_interface=-1
          if len(x) != len('cdp-interface') and help: cl_cdp_interface=None
          continue
        if cmp('serial-number'[0:len(x)], x) == 0:
          try: cl_serial_number = argv.pop(0)
          except: 
            if help: cl_serial_number=-1
          if len(x) != len('serial-number') and help: cl_serial_number=None
          continue
        if cmp('protocol'[0:len(x)], x) == 0:
          try: cl_protocol = argv.pop(0); 
          except: 
            if help: cl_protocol=-1
          if len(x) != len('protocol') and help: cl_protocol=None
          if cl_protocol: protocol=cl_protocol
          continue
        if cmp('download-only'[0:len(x)], x) == 0:
          cl_download_only = 1
          continue
        print("Syntax Error|invalid token:", x)
        exit(-1)
  

########### display online help (if asked for) #################
nb_args = len(sys.argv)
if nb_args > 1:
  m = re.match('__cli_script.*help', sys.argv[1])
  if m:
    # first level help: display script description
    if sys.argv[1] == "__cli_script_help":
      print("loads system/kickstart images and config file for POAP\n")
      exit(0)
    # argument help
    argv = sys.argv[2:]
    # dont count last arg if it was partial help (no-space-question-mark)
    if sys.argv[1] == "__cli_script_args_help_partial":
      argv = argv[:-1]
    parse_args(argv, "help")
    if cl_serial_number==-1:
      print("WORD|Enter the serial number")
      exit(0)
    if cl_cdp_interface==-1:
      print("WORD|Enter the CDP interface instance")
      exit(0)
    if cl_protocol==-1:
      print("tftp|Use tftp for file transfer protocol")
      print("ftp|Use ftp for file transfer protocol")
      print("scp|Use scp for file transfer protocol")
      exit(0)
    if not cl_serial_number:
      print("serial-number|The serial number to use for the config filename")
    if not cl_cdp_interface:
      print("cdp-interface|The CDP interface to use for the config filename")
    if not cl_protocol:
      print("protocol|The file transfer protocol")
    if not cl_download_only:
      print("download-only|stop after download, dont write boot variables")
    print("<CR>|Run it (use static name for config file)")
    # we are done
    exit(0)

# *** now overwrite env vars with command line vars (if any given)
# if we get here it is the real deal (no online help case)

argv = sys.argv[1:]
parse_args(argv)
if cl_serial_number != None: 
    serial_number=cl_serial_number
    config_file_type = "serial_number"
if cl_cdp_interface: 
    cdp_interface=cl_cdp_interface
    config_file_type = "location"
if cl_protocol: 
    protocol=cl_protocol
# setup log file and associated utils

if now == None:
    now=cli("show clock | sed 's/[ :]/_/g'");

try:
    log_filename = "%s.%s" % (log_filename, now)
except Exception as inst:
    print(inst)
poap_log_file = open(log_filename, "w+")

def poap_log (info):
    poap_log_file.write(info)
    poap_log_file.write("\n")
    poap_log_file.flush()
    print(info)
    sys.stdout.flush()

def poap_log_close ():
    poap_log_file.close()

def abort_cleanup_exit () : 
    poap_log("INFO: cleaning up")
    poap_log_close()
    exit(-1)

def run_cli (cmd):
    poap_log("CLI : %s" % cmd)
    r=cli(cmd)

    return r

# some argument sanity checks:

if config_file_type == "serial_number" and serial_number == None: 
    poap_log("ERR: serial-number required (to derive config name) but none given")
    exit(-1)

if config_file_type == "location" and cdp_interface == None: 
    poap_log("ERR: interface required (to derive config name) but none given")
    exit(-1)

# images are copied to temporary location first (dont want to 
# overwrite good images with bad ones).
system_image_dst_tmp    = "%s/system.img_temp"    % (image_dir_dst)
kickstart_image_dst_tmp = "%s/kickstart.img_temp" % (image_dir_dst)

system_image_src    = "%s/%s" % (image_dir_src, target_system_image)
kickstart_image_src = "%s/%s" % (image_dir_src, target_kickstart_image)

# cleanup stuff from a previous run
# by deleting the tmp destination for image files and then recreating the
# directory
image_dir_dst_u="/%s" % image_dir_dst.replace(":", "/") # unix path: cli's rmdir not working!
try: shutil.rmtree("%s" % image_dir_dst_u)
except: pass

run_cli("mkdir %s" % image_dir_dst)
# if not os.path.exists(image_dir_dst_u):
#    os.mkdir(image_dir_dst_u)

# setup the cli session
cli("no terminal color persist")
cli("terminal dont-ask")
cli("terminal password %s" % password)


def rm_rf (filename): 
    try: cli("delete %s" % filename)
    except: pass

# signal handling
def sig_handler_no_exit (signum, frame) : 
    poap_log("INFO: SIGTERM Handler while configuring boot variables")

def sigterm_handler (signum, frame): 
    poap_log("INFO: SIGTERM Handler") 
    abort_cleanup_exit()
    exit(1)

signal.signal(signal.SIGTERM, sigterm_handler)

# transfers file, return True on success; on error exits unless 'fatal' is False in which case we return False
def doCopy(protocol = "", host = "", source = "", dest = "", vrf = "management", login_timeout=10, user = "", password = "", fatal=True):
    rm_rf(dest)

    # mess with source paths (tftp does not like full paths)
    global username, ftp_username
    # if protocol=="tftp": 
      # source=source[6:]
    if protocol=="ftp": 
      username=ftp_username
      # source=source[6:]

    cmd="config terminal ; terminal password %s ; copy %s://%s@%s/%s %s" % (password, protocol, username, host, source, dest)
    print(cmd)
    try: run_cli(cmd)
    except:
        poap_log("WARN: Copy Failed: %s" % str(sys.exc_info()[1]).strip('\n\r'))
        if fatal:
            poap_log("ERR : aborting")
            abort_cleanup_exit()
            exit(1)
        return False
    return True


def get_md5sum_src (file_name):
    md5_file_name_src = "%s.%s" % (file_name, md5sum_ext_src)
    md5_file_name_dst = "volatile:%s.poap_md5" % os.path.basename(md5_file_name_src)
    rm_rf(md5_file_name_dst)

    ret=doCopy(protocol, hostname, md5_file_name_src, md5_file_name_dst, vrf, md5sum_timeout, username, password, False)
    if ret == True:
        sum=run_cli("show file %s | grep -v '^#' | head lines 1 | sed 's/ .*$//'" % md5_file_name_dst).strip('\n')
        poap_log("INFO: md5sum %s (.md5 file)" % sum)
        rm_rf(md5_file_name_dst)
        return sum
    return None
    # if no .md5 file, and text file, could try to look for an embedded checksum (see below)


def check_embedded_md5sum (filename):
    # extract the embedded checksum
    sum_emb=run_cli("show file %s | grep '^#md5sum' | head lines 1 | sed 's/.*=//'" % filename).strip('\n')
    if sum_emb == "":
        poap_log("INFO: no embedded checksum")
        return None
    poap_log("INFO: md5sum %s (embedded)" % sum_emb)

    # remove the embedded checksum (create temp file) before we recalculate
    cmd="show file %s exact | sed '/^#md5sum=/d' > volatile:poap_md5" % filename
    run_cli(cmd)
    # calculate checksum (using temp file without md5sum line)
    sum_dst=run_cli("show file volatile:poap_md5 md5sum").strip('\n')
    poap_log("INFO: md5sum %s (recalculated)" % sum_dst)
    try: run_cli("delete volatile:poap_md5")
    except: pass
    if sum_emb != sum_dst:
        poap_log("ERR : MD5 verification failed for %s" % filename)
        abort_cleanup_exit()

    return None

def get_md5sum_dst (filename):
    sum=run_cli("show file %s md5sum" % filename).strip('\n')
    poap_log("INFO: md5sum %s (recalculated)" % sum)
    return sum  

def check_md5sum (filename_src, filename_dst, lname):
    md5sum_src = get_md5sum_src(filename_src)
    if md5sum_src: # we found a .md5 file on the server
            md5sum_dst = get_md5sum_dst(filename_dst)
            if md5sum_dst != md5sum_src:
                 poap_log("ERR : MD5 verification failed for %s! (%s)" % (lname, filename_dst))
                 abort_cleanup_exit()

# Will run our CLI command to test MD5 checksum and if files are valid images
# This check is also performed while setting the boot variables, but this is an
# additional check

def get_md5_status (msg):
   
    lines=msg.split("\n") 
    for line in lines:
        index=line.find("MD5")
        if (index!=-1):
            status=line[index+17:]
            return status

def get_version (msg):
   
    lines=msg.split("\n") 
    for line in lines:
        index=line.find("MD5")
        if (index!=-1):
            status=line[index+17:]

        index=line.find("kickstart:")
        if (index!=-1): 
            index=line.find("version")
            ver=line[index:]
            return ver

        index=line.find("system:")
        if (index!=-1):
            index=line.find("version")
            ver=line[index:]
            return ver
    
def verify_images2 ():
    kick_cmd="show version image %s" % kickstart_image_dst
    sys_cmd="show version image %s" % system_image_dst
    kick_msg=run_cli(kick_cmd)
    sys_msg=run_cli(sys_cmd)

    # n3k images do not provide md5 information
    
    kick_s=get_md5_status(kick_msg)
    sys_s=get_md5_status(sys_msg)    

    kick_v=get_version(kick_msg)
    sys_v=get_version(sys_msg)    
    
    
    print("MD5 status: %s and %s" % (kick_s, sys_s))
    if (kick_s == "Passed" and sys_s == "Passed"):
        # MD5 verification passed
        if(kick_v != sys_v): 
            poap_log("ERR : Image version mismatch. (kickstart : %s) (system : %s)" % (kick_v, sys_v))
            abort_cleanup_exit()
    else:
        poap_log("ERR : MD5 verification failed!")
        poap_log("%s\n%s" % (kick_msg, sys_msg))
        abort_cleanup_exit()
    poap_log("INFO: Verification passed. (kickstart : %s) (system : %s)" % (kick_v, sys_v))
    return True

def verify_images ():
    kick_cmd="show version image %s" % kickstart_image_dst
    sys_cmd="show version image %s" % system_image_dst
    kick_msg=run_cli(kick_cmd)
    sys_msg=run_cli(sys_cmd)
    kick_v=kick_msg.split()
    sys_v=sys_msg.split()
    print("Values: %s and %s" % (kick_v[2], sys_v[2]))
    if (kick_v[2] == "Passed" and sys_v[2] == "Passed"):
        # MD5 verification passed
        if(kick_v[8] != sys_v[10]):
            poap_log("ERR : Image version mismatch. (kickstart : %s) (system : %s)" % (kick_v[8], sys_v[10]))
            abort_cleanup_exit()
    else:
        poap_log("ERR : MD5 verification failed!")
        poap_log("%s\n%s" % (kick_msg, sys_msg))
        abort_cleanup_exit()
    poap_log("INFO: Verification passed. (kickstart : %s) (system : %s)" % (kick_v[8], sys_v[10]))
    return True


# get config file from server
def get_config ():

    doCopy (protocol, hostname, config_file_src, config_file_dst, vrf, config_timeout, username, password)
    poap_log("INFO: Completed Copy of Config File") 
        
    # get file's md5 from server (if any) and verify it, failure is fatal (exit)
    check_md5sum (config_file_src, config_file_dst, "config file")


# get system image file from server
def get_system_image ():

    doCopy (protocol, hostname, system_image_src, system_image_dst_tmp, vrf, system_timeout, username, password)  
    poap_log("INFO: Completed Copy of System Image" ) 
    
    # get file's md5 from server (if any) and verify it, failure is fatal (exit)
    check_md5sum (system_image_src, system_image_dst_tmp, "system image")
    run_cli ("move %s %s" % (system_image_dst_tmp, system_image_dst))


# get kickstart image file from server
def get_kickstart_image ():

    doCopy (protocol, hostname, kickstart_image_src, kickstart_image_dst_tmp, vrf, kickstart_timeout, username, password)  
    poap_log("INFO: Completed Copy of Kickstart Image") 
    
    # get file's md5 from server (if any) and verify it, failure is fatal (exit)
    check_md5sum (kickstart_image_src, kickstart_image_dst_tmp, "kickstart image")
    run_cli ("move %s %s" % (kickstart_image_dst_tmp, kickstart_image_dst))


def wait_box_online ():
	
    while 1:
        r=int(run_cli("show system internal platform internal info | grep box_online | sed 's/[^0-9]*//g'").strip('\n'))
        if r==1: break
        else: time.sleep(5)
        poap_log("INFO: Waiting for box online...") 


# install (make persistent) images and config 
def install_it (): 
    global cl_download_only
    if cl_download_only: exit(0)
    timeout = -1

    # make sure box is online
    wait_box_online()

    poap_log("INFO: Setting the boot variables")
    # TODO: check image first, else if second image bad we are dead
    # We moved the images from the tmp dir to the dest dir so we can now delete
    # the tmp directory
    # try: shutil.rmtree("%s" % image_dir_dst_u)
    # except: pass
    try:
        run_cli ("config terminal ; boot kickstart %s" % kickstart_image_dst)
        run_cli ("config terminal ; boot system %s" % system_image_dst)
        run_cli ("copy running-config startup-config")
        run_cli ('copy %s scheduled-config' % config_file_dst)
    except:
        poap_log("ERR : setting bootvars or copy run start failed!")
        poap_log("ERR: msg: %s" % str(sys.exc_info()[1]).strip('\n\r'))
        traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        abort_cleanup_exit()
    # no need to delete config_file_dst, it is in /volatile and we will reboot....
    # do it anyway so we don't have permission issues when testing script and
    # running as different users (log file have timestamp, so fine)
    poap_log("INFO: Configuration successful")

        
# Verify if free space is available to download config, kickstart and system images
def verify_freespace (): 

    freespace=int(run_cli("dir bootflash: | last 3 | grep free | sed 's/[^0-9]*//g'").strip('\n'))
    freespace=freespace / 1024

    #s = os.statvfs("/bootflash/")
    #reespace = (s.f_bavail * s.f_frsize) / 1024
    poap_log("INFO: free space is %s kB"  % freespace )

    if required_space > freespace:
        poap_log("ERR : Not enough space to copy the config, kickstart image and system image, aborting!")
        abort_cleanup_exit()


# figure out config filename to download based on serial-number
def set_config_file_src_serial_number (): 
    global config_file_src
    config_file_src = "%s.%s" % (config_file_src, serial_number)
    poap_log("INFO: Selected config filename (serial-nb) : %s" % config_file_src)


# figure out config filename to download based on cdp neighbor info
# sample output:
#   switch# show cdp neig
#   Capability Codes: R - Router, T - Trans-Bridge, B - Source-Route-Bridge
#                     S - Switch, H - Host, I - IGMP, r - Repeater,
#                     V - VoIP-Phone, D - Remotely-Managed-Device,
#                     s - Supports-STP-Dispute, M - Two-port Mac Relay
#
#   Device ID              Local Intrfce   Hldtme  Capability  Platform      Port ID
#   Switch                 mgmt0           148     S I         WS-C2960G-24T Gig0/2
#   switch(Nexus-Switch)   Eth1/1          150     R S I s     Nexus-Switch  Eth2/1
#   switch(Nexus-Switch)   Eth1/2          150     R S I s     Nexus-Switch  Eth2/2
# in xml:
#   <ROW_cdp_neighbor_brief_info>
#    <ifindex>83886080</ifindex>
#    <device_id>Switch</device_id>
#    <intf_id>mgmt0</intf_id>
#    <ttl>137</ttl>
#    <capability>switch</capability>
#    <capability>IGMP_cnd_filtering</capability>
#    <platform_id>cisco WS-C2960G-24TC-L</platform_id>
#    <port_id>GigabitEthernet0/4</port_id>
#   </ROW_cdp_neighbor_brief_info>

def set_config_file_src_location():
    global config_file_src
    cmd = "show cdp neighbors interface %s" % cdp_interface
    poap_log("CLI: %s" % cmd)
    try: r = run_cli(cmd);
    except: 
        poap_log("ERR: cant get neighbor info on %s", cdp_interface)
        exit(-1)

    
    lines=r.split("\n")

    try:
        idx = [i for i, line in enumerate(lines) if re.search('^.*Device-ID.*$', line)]
        words=lines[idx[0]+1].split()
        switchName=words[0]
        intfName = words[len(words)-1]
    except:
        poap_log("ERR: unexpected 'show cdp neigbhor' output: %s" % r)
        exit(-1)
    neighbor = "%s_%s" % (switchName, intfName)
    neighbor = string.replace(neighbor, "/", "_")
    config_file_src = "%s.%s" % (config_file_src, neighbor)
    poap_log("INFO: Selected config filename (cdp-neighbor) : %s" % config_file_src)

# set complete name of config_file_src based on serial-number/interface (add extension)

if config_file_type == "location": 
    #set source config file based on location
    set_config_file_src_location()

elif config_file_type == "serial_number": 
    #set source config file based on switch's serial number
    set_config_file_src_serial_number()


# finaly do it

verify_freespace()
get_kickstart_image()
get_system_image()
verify_images2()
get_config()

# dont let people abort the final stage that concretize everything
# not sure who would send such a signal though!!!! (sysmgr not known to care about vsh)
signal.signal(signal.SIGTERM, sig_handler_no_exit)
install_it()

poap_log_close()
exit(0)

