#!/usr/bin/env python
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim
import atexit
import sys
import argparse


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('--vc-host',
                        required=True,
                        help='vSpehre server host')

    parser.add_argument('--vc-port',
                        type=int,
                        default=443,
                        help='vSphere server port')

    parser.add_argument('--vc-user',
                        required=True,
                        help='vSphere user name')

    parser.add_argument('--vc-pass',
                        required=True,
                        help='vSphere user password')

    parser.add_argument('--dvs-uuid',
                        required=True,
                        help='DVS UUID')

    args = parser.parse_args()
    return args


def get_dvs_by_uuid(content, uuid):
    dvs = content.dvSwitchManager.QueryDvsByUuid(uuid=uuid)
    return dvs


def get_dvs_ports(dvs):
    criteria = vim.dvs.PortCriteria()
    criteria.inside = True
    criteria.uplinkPort = False
    ports = dvs.FetchDVPorts(criteria=criteria)
    name_to_ports = {}
    for p in ports:
        if p.config and p.config.name:
            if not name_to_ports.get(p.config.name):
                name_to_ports[p.config.name] = []
            name_to_ports[p.config.name].append(p)
    return name_to_ports


def report_dvs_port_name_duplications(dvs_ports):
    duplicates_exist = False
    for name in dvs_ports:
        ports = dvs_ports[name]
        if len(ports) > 1:
            duplicates_exist = True
            print('Multiple ports named %s:' % name)
            for p in ports:
                print('PG key: %s, Connected: %s' % (
                    p.portgroupKey,
                    (p.connectee is not None)))
    if not duplicates_exist:
        print('No port name duplications.')


def main():
    args = get_args()

    service_instance = SmartConnect(host=args.vc_host,
                                    user=args.vc_user,
                                    pwd=args.vc_pass,
                                    port=args.vc_port)
    atexit.register(Disconnect, service_instance)
    content = service_instance.RetrieveContent()

    dvs = get_dvs_by_uuid(content, args.dvs_uuid)
    dvs_ports = get_dvs_ports(dvs)
    report_dvs_port_name_duplications(dvs_ports)


if __name__ == "__main__":
    sys.exit(main())
