#!/usr/bin/env python
from pyVim.connect import SmartConnection
from pyVmomi import vim, vmodl
import sys
import argparse
from openstack import connection as os_connection
import hashlib
import time


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


def get_portgroup_name(dvs_uuid, sg_set):
    dvs_id = dvs_uuid.translate(None, ' -')[:8]
    name = sg_set + '-' + dvs_id
    if len(name) > 80:
        hex = hashlib.sha224()
        hex.update(sg_set)
        name = hex.hexdigest() + '-' + dvs_id
    return name


def print_subreport_heading(heading):
    msg = '\n\n%s (started at %s)' % (heading, time.ctime())
    print(msg)
    print('-' * len(msg))


def report_dvs_port_name_duplications(dvs_ports):
    print_subreport_heading('DVS port name duplications')
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


def report_connectee_consistency(dvs_ports, os_ports, vm_ref_to_props):
    print_subreport_heading('Connectee (device ID) consistency')
    connected_devices_match = True
    for os_port in os_ports:
        for dvs_port in dvs_ports:
            if os_port.id == dvs_port.config.name:
                vm_inst_uuid = None
                if dvs_port.connectee:
                    vm_ref = dvs_port.connectee.connectedEntity
                    vm_inst_uuid = (vm_ref_to_props[vm_ref]
                                    ['config.instanceUuid'])
                if vm_inst_uuid != os_port.device_id:
                    connected_devices_match = False
                    print('Inconsistent connectees for port %s: VC VM '
                          'instanceUuid (%s) != OS port device_id (%s)' %
                          (os_port.id,
                           vm_inst_uuid,
                           os_port.device_id))
    if connected_devices_match:
        print('No inconsistencies between VC ports connectee instanceUuid and '
              'OS ports device_id.')


def report_pg_sg_consistency(dvs_uuid, os_ports, pg_ref_to_props,
                             vm_ref_to_props):
    print_subreport_heading(
        'VM portgroup consistency with OS port security group')
    os_port_device_id_to_sg_sets = {}
    for os_port in os_ports:
        sg_set = [os_port.network_id]
        if os_port.security_groups:
            sg_set.append(','.join(os_port.security_groups))
        sg_set = ':'.join(sg_set)
        if not os_port_device_id_to_sg_sets.get(os_port.device_id):
            os_port_device_id_to_sg_sets[os_port.device_id] = []
        os_port_device_id_to_sg_sets[os_port.device_id].append(sg_set)
    portgroups_match = True
    for vm_ref, vm_props in vm_ref_to_props.items():
        sg_sets = (os_port_device_id_to_sg_sets.get(
            vm_props['config.instanceUuid'])
                   or [])
        expected_pg_names = set([get_portgroup_name(dvs_uuid, sg_set)
                                 for sg_set in sg_sets])
        actual_pg_names = set([pg_ref_to_props[pg_ref]['name']
                               for pg_ref in vm_props['network']])
        os_only_pgs = expected_pg_names - actual_pg_names
        dvs_only_pgs = actual_pg_names - expected_pg_names
        if os_only_pgs or dvs_only_pgs:
            portgroups_match = False
            print('Inconsistent portgroups for VM ref %s '
                  '(device_id/instanceUuid %s):' %
                  (vm_ref, vm_props['config.instanceUuid']))
            if os_only_pgs:
                print('  Expected but missing connection to PGs:\n    %s'
                      % '\n    '.join(os_only_pgs))
            if dvs_only_pgs:
                print('  Unexpected but present connection to PGs:\n    %s'
                      % '\n    '.join(dvs_only_pgs))
    if portgroups_match:
        print('No inconsistencies between VC VM portgroup connections and OS '
              'ports security groups.')


def report_port_mapping(dvs_ports, os_ports):
    print_subreport_heading('Port mapping')
    os_port_ids = set([p.id for p in os_ports])
    dvs_port_names = set([p.config.name for p in dvs_ports])
    dvs_only_ports = dvs_port_names - os_port_ids
    os_only_ports = os_port_ids - dvs_port_names
    print('vSphere-only ports:\n  %s' % '\n  '.join(dvs_only_ports))
    print('OpenStack-only ports:\n  %s' % '\n  '.join(os_only_ports))


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
                                          ['name'])
        pg_ref_to_props = get_mo_ref_to_props(content, pgs_filter_spec)

        report_dvs_port_name_duplications(dvs_ports)

        with os_connection.Connection(cloud='envvars') as os_conn:
            os_ports = os_conn.list_ports(
                {'binding:host_id': args.os_compute_host})
            os_ports = [p for p in os_ports
                        if p.get('binding:vif_type') == 'dvs']
            report_connectee_consistency(dvs_ports, os_ports, vm_ref_to_props)
            report_pg_sg_consistency(args.dvs_uuid, os_ports, pg_ref_to_props,
                                     vm_ref_to_props)
            report_port_mapping(dvs_ports, os_ports)

    print('Report end: %s' % time.ctime())


if __name__ == "__main__":
    sys.exit(main())
