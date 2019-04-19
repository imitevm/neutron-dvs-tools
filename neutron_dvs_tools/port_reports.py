import utils


def report_dvs_port_name_duplications(dvs_ports):
    utils.print_stage_heading('DVS port name duplications')
    name_to_ports = {}
    for p in dvs_ports:
        if p.config.name:
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
    utils.print_stage_heading('Connectee (device ID) consistency')
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
    utils.print_stage_heading(
        'VM portgroup consistency with OS port security group')
    os_port_device_id_to_pg_names = {}
    for os_port in os_ports:
        pg_name = utils.get_portgroup_name(dvs_uuid, os_port)
        if not os_port_device_id_to_pg_names.get(os_port.device_id):
            os_port_device_id_to_pg_names[os_port.device_id] = []
        os_port_device_id_to_pg_names[os_port.device_id].append(pg_name)
    portgroups_match = True
    for vm_ref, vm_props in vm_ref_to_props.items():
        expected_pg_names = set(
            os_port_device_id_to_pg_names.get(
                vm_props['config.instanceUuid'],
                []))
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
    utils.print_stage_heading('Port mapping')
    os_port_ids = set([p.id for p in os_ports])
    dvs_port_names = set([p.config.name for p in dvs_ports])
    dvs_only_ports = dvs_port_names - os_port_ids
    os_only_ports = os_port_ids - dvs_port_names
    print('vSphere-only ports:\n  %s' % '\n  '.join(dvs_only_ports))
    print('OpenStack-only ports:\n  %s' % '\n  '.join(os_only_ports))
