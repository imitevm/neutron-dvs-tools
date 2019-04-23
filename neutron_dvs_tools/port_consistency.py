#!/usr/bin/env python
from pyVim.connect import SmartConnection
from pyVmomi import vim, vmodl
import sys
import argparse
from openstack import connection as os_connection
import time
import port_resolver
import port_reports


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument('--vc-host',
                        required=True,
                        help='vSpehre server hostname')

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

    parser.add_argument('--os-compute-host',
                        required=True,
                        help='OpenStack compute host name')

    parser.add_argument('--align-vc',
                        action='store_true',
                        default=False,
                        help='Flag to align DVS ports to OpenStack')

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
            if is_dvs_port_in_scope(p)]


def is_dvs_port_in_scope(p):
    connected_to_vm = (p.connectee and p.connectee.type ==
                       vim.dvs.PortConnectee.ConnecteeType.vmVnic)
    named_but_disconnected = p.config and p.config.name and not p.connectee
    return connected_to_vm or named_but_disconnected


def get_mo_ref_to_props(content, filter_spec):
    options = vmodl.query.PropertyCollector.RetrieveOptions()
    mo_ref_to_props = {}
    result = content.propertyCollector.RetrievePropertiesEx([filter_spec],
                                                            options)
    while result:
        for res in result.objects:
            mo_ref_to_props[res.obj] = {p.name: p.val for p in res.propSet}
        if result.token:
            result = content.propertyCollector.ContinueRetrievePropertiesEx(
                token=result.token)
        else:
            result = None
    return mo_ref_to_props


def get_filter_spec(start_moref, start_type, path, target_type, prop_path_set):
    trav_spec = vmodl.query.PropertyCollector.TraversalSpec(
        type=start_type,
        path=path,
        skip=False)
    obj_specs = [
        vmodl.query.PropertyCollector.ObjectSpec(obj=start_moref, skip=True,
                                                 selectSet=[trav_spec])]
    filter_spec = vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = obj_specs
    prop_set = vmodl.query.PropertyCollector.PropertySpec(all=False)
    prop_set.type = target_type
    prop_set.pathSet = prop_path_set
    filter_spec.propSet = [prop_set]
    return filter_spec


def main():
    args = get_args()
    print('Report start: %s' % time.ctime())

    with SmartConnection(host=args.vc_host,
                         user=args.vc_user,
                         pwd=args.vc_pass,
                         port=args.vc_port) as service_instance:
        content = service_instance.RetrieveContent()

        dvs = get_dvs_by_uuid(content, args.dvs_uuid)
        dvs_ports = get_dvs_ports(dvs)
        vms_filter_spec = get_filter_spec(dvs, vim.DistributedVirtualSwitch,
                                          'summary.vm',
                                          vim.VirtualMachine,
                                          ['config.instanceUuid', 'network'])
        vm_ref_to_props = get_mo_ref_to_props(content, vms_filter_spec)

        pgs_filter_spec = get_filter_spec(dvs, vim.DistributedVirtualSwitch,
                                          'portgroup',
                                          vim.dvs.DistributedVirtualPortgroup,
                                          ['name', 'key'])
        pg_ref_to_props = get_mo_ref_to_props(content, pgs_filter_spec)

        port_reports.report_dvs_port_name_duplications(dvs_ports)

        with os_connection.Connection(cloud='envvars') as os_conn:
            os_ports = os_conn.list_ports(
                {'binding:host_id': args.os_compute_host})
            os_ports = [p for p in os_ports
                        if p.get('binding:vif_type') == 'dvs']
            port_reports.report_connectee_consistency(dvs_ports, os_ports,
                                                      vm_ref_to_props)
            port_reports.report_pg_sg_consistency(args.dvs_uuid, os_ports,
                                                  pg_ref_to_props,
                                                  vm_ref_to_props)
            port_reports.report_port_mapping(dvs_ports, os_ports)

            if args.align_vc:
                port_resolver.align_vc_with_os(args.dvs_uuid, dvs_ports,
                                               os_ports, pg_ref_to_props,
                                               vm_ref_to_props, dvs,
                                               service_instance)

    print('\nReport end: %s' % time.ctime())


if __name__ == "__main__":
    sys.exit(main())
