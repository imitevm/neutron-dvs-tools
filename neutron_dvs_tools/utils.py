import time
import hashlib


def get_portgroup_name(dvs_uuid, os_port):
    sg_set = [os_port.network_id]
    if os_port.security_groups:
        sg_set.append(','.join(os_port.security_groups))
    sg_set = ':'.join(sg_set)
    dvs_id = dvs_uuid.translate(None, ' -')[:8]
    name = sg_set + '-' + dvs_id
    if len(name) > 80:
        hex = hashlib.sha224()
        hex.update(sg_set)
        name = hex.hexdigest() + '-' + dvs_id
    return name


def print_stage_heading(heading):
    msg = '\n\n%s (started at %s)' % (heading, time.ctime())
    print(msg)
    print('-' * len(msg))