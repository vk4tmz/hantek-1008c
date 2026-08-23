#!/usr/bin/env python3
import sys
import usb.core
import usb.util
VID=0x0783
PID=0x5725

def endpoint_type(attrs):
    return {0:'control',1:'isochronous',2:'bulk',3:'interrupt'}.get(attrs & 0x03,'unknown')

def safe_string(dev,index):
    if not index: return None
    try:
        value=usb.util.get_string(dev,index)
        return value.rstrip('\x00') if value is not None else None
    except Exception as exc:
        return f'<unavailable: {exc}>'

def main():
    print(f'Looking for Hantek 1008C {VID:04x}:{PID:04x}...')
    dev=usb.core.find(idVendor=VID,idProduct=PID)
    if dev is None:
        print('ERROR: device not found',file=sys.stderr); return 1
    print('Device found')
    print(f'  VID:PID        {dev.idVendor:04x}:{dev.idProduct:04x}')
    print(f'  USB version    {dev.bcdUSB >> 8:x}.{dev.bcdUSB & 0xff:02x}')
    print(f'  device ver     {dev.bcdDevice >> 8:x}.{dev.bcdDevice & 0xff:02x}')
    print(f'  configurations {dev.bNumConfigurations}')
    print(f'  manufacturer   {safe_string(dev,dev.iManufacturer)!r}')
    print(f'  product        {safe_string(dev,dev.iProduct)!r}')
    print(f'  serial         {safe_string(dev,dev.iSerialNumber)!r}')
    try:
        cfg=dev.get_active_configuration()
    except usb.core.USBError as exc:
        print(f'ERROR: unable to read active configuration: {exc}',file=sys.stderr); return 2
    print(f'\nActive configuration: {cfg.bConfigurationValue}')
    for intf in cfg:
        print(f'Interface {intf.bInterfaceNumber}, alt {intf.bAlternateSetting}: class=0x{intf.bInterfaceClass:02x} subclass=0x{intf.bInterfaceSubClass:02x} protocol=0x{intf.bInterfaceProtocol:02x}')
        for ep in intf:
            direction='IN' if usb.util.endpoint_direction(ep.bEndpointAddress)==usb.util.ENDPOINT_IN else 'OUT'
            print(f'  endpoint 0x{ep.bEndpointAddress:02x} {direction:3s} {endpoint_type(ep.bmAttributes):4s} max_packet={ep.wMaxPacketSize}')
    print('\nEnumeration complete; no protocol commands were sent.')
    return 0
if __name__=='__main__': raise SystemExit(main())
