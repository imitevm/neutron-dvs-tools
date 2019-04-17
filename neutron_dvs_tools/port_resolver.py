import utils
from pyVim.task import WaitForTask
from pyVmomi import vim


def align_vc_with_os(dvs_uuid, dvs_ports, os_ports, pg_ref_to_props,
                     vm_ref_to_props, dvs, service_instance):
    print('\nAlign vCenter ports with OpenStack')

    # Build PortInfo collections for DVS and OpenStack ports
    dvs_pis = []
    for dvs_port in dvs_ports:
        pi = make_dvs_pi(dvs_port, pg_ref_to_props, vm_ref_to_props)
        dvs_pis.append(pi)

    os_pis = []
    for os_port in os_ports:
        pi = PortInfo(os_port.id,
                      utils.get_portgroup_name(dvs_uuid, os_port),
                      os_port.device_id,
                      os_port)
        os_pis.append(pi)

    # Remove matching ports from collections; single DVS port per OS port
    for oi in range_reverse_list_iter(os_pis):
        os_pi = os_pis[oi]
        for di in range_reverse_list_iter(dvs_pis):
            dvs_pi = dvs_pis[di]
            if (os_pi.port_id == dvs_pi.port_id and
                    os_pi.pg_name == dvs_pi.pg_name and
                    os_pi.device_id == dvs_pi.device_id):
                os_pis.pop(oi)
                dvs_pis.pop(di)
                break

    rename_misnamed_dvs_ports(os_pis, dvs_pis, dvs, service_instance)

    move_misplaced_dvs_ports(os_pis, dvs_pis, pg_ref_to_props, dvs,
                             service_instance)

    utils.print_stage_heading('Disconnecting misconnected DVS ports')
    for dvs_pi in dvs_pis:
        dvs_port = dvs_pi.backing
        disconnect_dvs_port(dvs_port, vm_ref_to_props, service_instance)

    # TODO: Where only device_id differs => Connect to VM if exists

    # TODO: Connect VMs (from OS ports device_id) to portgroups

    # TODO: Rename ports - DVS ports to blank and new ports (from OS) to device_id


def rename_misnamed_dvs_ports(os_pis, dvs_pis, dvs, service_instance):
    utils.print_stage_heading('Renaming misnamed DVS ports')
    for oi in range_reverse_list_iter(os_pis):
        os_pi = os_pis[oi]
        for di in range_reverse_list_iter(dvs_pis):
            dvs_pi = dvs_pis[di]
            if (os_pi.port_id != dvs_pi.port_id and
                    os_pi.pg_name == dvs_pi.pg_name and
                    os_pi.device_id == dvs_pi.device_id):
                dvs_port = dvs_pi.backing
                spec = vim.DVPortConfigSpec(operation='edit')
                spec.name = os_pi.port_id
                spec.key = dvs_port.key
                spec.configVersion = dvs_port.config.configVersion
                try:
                    task = dvs.ReconfigureDVPort_Task(port=[spec])
                    WaitForTask(task, si=service_instance)
                    print('Renamed DVS port from %s to %s.' %
                          (dvs_pi.backing.name, spec.name))

                    os_pis.pop(oi)
                    dvs_pis.pop(di)
                    break
                except vim.fault.VimFault as e:
                    print_err('Failed renaming DVS port from %s to %s.' %
                              (dvs_pi.backing.name, spec.name),
                              exc=e)


def move_misplaced_dvs_ports(os_pis, dvs_pis, pg_ref_to_props, dvs,
                             service_instance):
    utils.print_stage_heading('Moving misplaced DVS ports to correct portgroup')
    for oi in range_reverse_list_iter(os_pis):
        os_pi = os_pis[oi]
        for di in range_reverse_list_iter(dvs_pis):
            dvs_pi = dvs_pis[di]
            if (os_pi.port_id == dvs_pi.port_id and
                    os_pi.pg_name != dvs_pi.pg_name and
                    os_pi.device_id == dvs_pi.device_id):
                os_pg_key = None
                for pg in pg_ref_to_props.values():
                    if pg['name'] == os_pi.pg_name:
                        os_pg_key = pg['key']
                        break
                if not os_pg_key:
                    print_err('Could not move DVS port %s to portgroup %s '
                              'since no portgroup found for that name.' %
                              (dvs_pi.port_id, os_pi.pg_name))
                    break
                try:
                    task = dvs.MoveDVPort_Task(
                        portKey=[dvs_pi.backing.key],
                        destinationPortgroupKey=os_pg_key)
                    WaitForTask(task, si=service_instance)
                    print('Moved DVS port %s from portgroup %s to %s.' %
                          (dvs_pi.port_id, dvs_pi.pg_name, os_pi.pg_name))

                    os_pis.pop(oi)
                    dvs_pis.pop(di)
                    break
                except vim.fault.VimFault as e:
                    print_err('Failed moving DVS port %s from portgroup %s to '
                              '%s.' % (dvs_pi.port_id,
                                       dvs_pi.pg_name,
                                       os_pi.pg_name),
                              exc=e)


def disconnect_dvs_port(dvs_port, vm_ref_to_props, service_instance):
    vm_ref = dvs_port.connectee.connectedEntity
    nic_device = vim.vm.device.VirtualDevice()
    nic_device.key = dvs_port.connectee.nicKey
    device_spec = vim.vm.device.VirtualDeviceSpec()
    device_spec.device = nic_device
    device_spec.operation = vim.vm.device.VirtualDeviceSpec.Operation.remove
    config_spec = vim.vm.ConfigSpec(deviceChange=[device_spec])
    try:
        task = vm_ref.ReconfigVM_Task(spec=config_spec)
        WaitForTask(task, si=service_instance)
        print('Disconnected DVS port %s (VM instanceUuid = %s).' %
              (dvs_port.name,
               vm_ref_to_props[vm_ref]['config.instanceUuid']))
    except vim.fault.VimFault as e:
        print_err('Failed disconnecting DVS port %s (VM instanceUuid = %s).' %
                  (dvs_port.name,
                   vm_ref_to_props[vm_ref]['config.instanceUuid']),
                  exc=e)


def make_dvs_pi(dvs_port, pg_ref_to_props, vm_ref_to_props):
    vm_inst_uuid = None
    if dvs_port.connectee:
        vm_ref = dvs_port.connectee.connectedEntity
        vm_inst_uuid = (vm_ref_to_props[vm_ref]
                        ['config.instanceUuid'])
    # Find PG mo ref by key
    for pg_ref, pg_props in pg_ref_to_props.iteritems():
        if dvs_port.portgroupKey == pg_props['key']:
            break
    pi = PortInfo(dvs_port.config.name,
                  pg_ref_to_props[pg_ref]['name'],
                  vm_inst_uuid,
                  dvs_port)
    return pi


def range_reverse_list_iter(list_):
    return range(len(list_) - 1, -1, -1)


def print_err(msg, exc=None):
    err_msg = '[ERROR] %s' % msg
    if exc:
        err_msg = '%s Exception: %s' % (err_msg, exc)
    print(err_msg)


class PortInfo:
    def __init__(self, port_id, pg_name, device_id, backing):
        self.port_id = port_id
        self.pg_name = pg_name
        self.device_id = device_id
        self.backing = backing