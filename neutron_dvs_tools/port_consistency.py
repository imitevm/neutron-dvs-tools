#!/usr/bin/env python
from pyVim.connect import SmartConnection
from pyVmomi import vim
import sys
import argparse
from openstack import connection as os_connection


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
    return [p for p in dvs.FetchDVPorts(criteria=criteria)
            if p.config and p.config.name]


def report_dvs_port_name_duplications(dvs_ports):
    name_to_ports = {}
    for p in dvs_ports:
        if not name_to_ports.get(p.config.name):
            name_to_ports[p.config.name] = []
        name_to_ports[p.config.name].append(p)

    duplicates_exist = False
    for name in name_to_ports:
        ports = name_to_ports[name]
        if len(ports) > 1:
            duplicates_exist = True
            print('Multiple ports named %s:' % name)
            for p in ports:
                print('PG key: %s, Connected: %s' % (
                    p.portgroupKey,
                    (p.connectee is not None)))
    if not duplicates_exist:
        print('No vSphere ports with duplicate names.')


def report_port_inconsistencies(dvs_ports, os_ports):
    dvs_port_names = set([p.config.name for p in dvs_ports])
    os_port_ids = set([p.id for p in os_ports])

    dvs_only_ports = dvs_port_names - os_port_ids
    os_only_ports = os_port_ids - dvs_port_names
    print('vSphere-only ports:\n%s' % '\n'.join(dvs_only_ports))
    print('OpenStack-only ports:\n%s' % '\n'.join(os_only_ports))


def main():
    args = get_args()

    with SmartConnection(host=args.vc_host,
                         user=args.vc_user,
                         pwd=args.vc_pass,
                         port=args.vc_port) as service_instance:
        content = service_instance.RetrieveContent()

        dvs = get_dvs_by_uuid(content, args.dvs_uuid)
        dvs_ports = get_dvs_ports(dvs)
        
    report_dvs_port_name_duplications(dvs_ports)

    with os_connection.Connection(cloud='envvars') as os_conn:
        os_ports = os_conn.network.ports()
        report_port_inconsistencies(dvs_ports, os_ports)


if __name__ == "__main__":
    sys.exit(main())
