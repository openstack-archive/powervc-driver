# Copyright 2013 IBM Corp.

'''
Created on Aug 2, 2013

@author: John Kasperski
'''
import fnmatch

from powervc.common.constants import LOCAL_OS
from powervc.common.constants import POWERVC_OS
from powervc.neutron.common import constants
from oslo.config import cfg
import json

from neutron.openstack.common import log as logging
LOG = logging.getLogger(__name__)

CONF = cfg.CONF


# Utility routines

def _compare_objects(local_obj, pvc_obj, db_obj,
                     update_fields, default_target):
    for field in update_fields:
        if pvc_obj.get(field) != local_obj.get(field):
            update_data = db_obj.get('update_data')
            if not update_data or len(update_data) == 0:
                return default_target
            try:
                update_dict = json.loads(update_data)
            except ValueError:
                pass
                update_dict = None
            if not update_dict:
                return default_target
            db_field = update_dict.get(field)
            if db_field != pvc_obj.get(field):
                return LOCAL_OS
            else:
                return POWERVC_OS
    return None


def compare_networks(local_net, pvc_net, db_net, default_target):
    return _compare_objects(local_net, pvc_net, db_net,
                            constants.NETWORK_UPDATE_FIELDS, default_target)


def compare_subnets(local_sub, pvc_sub, db_sub, default_target):
    return _compare_objects(local_sub, pvc_sub, db_sub,
                            constants.SUBNET_UPDATE_FIELDS, default_target)


def compare_ports(local_port, pvc_port, db_port, default_target):
    return _compare_objects(local_port, pvc_port, db_port,
                            constants.PORT_UPDATE_FIELDS, default_target)


def _equal_objects(obj1, obj2, update_fields):
    for field in update_fields:
        if obj1.get(field) != obj2.get(field):
            return False
    return True


def equal_networks(net1, net2):
    return _equal_objects(net1, net2, constants.NETWORK_UPDATE_FIELDS)


def equal_subnets(sub1, sub2):
    return _equal_objects(sub1, sub2, constants.SUBNET_UPDATE_FIELDS)


def equal_ports(port1, port2):
    return _equal_objects(port1, port2, constants.PORT_UPDATE_FIELDS)


def extract_ids_from_entry(obj):
    pvc_id = obj.get('pvc_id')
    local_id = obj.get('local_id')
    return (pvc_id, local_id)


def extract_subnets_from_port(port):
    subnets = []
    fixed_ips = port.get('fixed_ips')
    if not fixed_ips:
        return []
    for ip in fixed_ips:
        subnet = ip.get('subnet_id')
        if subnet and len(subnet) > 0:
            subnets.append(subnet)
    return subnets


def gen_network_sync_key(net):
    result = ''
    if 'provider:network_type' in net:
        result += net['provider:network_type']
    if 'provider:segmentation_id' in net:
        if net['provider:segmentation_id']:
            result += '_' + str(net['provider:segmentation_id'])
    if 'provider:physical_network' in net:
        if net['provider:physical_network']:
            result += '_' + net['provider:physical_network']
    return result


def gen_subnet_sync_key(sub, db_net):
    return sub['cidr'] + '_' + db_net['pvc_id']


def gen_port_sync_key(port, db_net):
    result = ''
    fixed_ips = port.get('fixed_ips')
    if not fixed_ips:
        return False
    for ip in fixed_ips:
        ipaddr = ip.get('ip_address')
        if ipaddr and '.' in ipaddr:
            if len(result) == 0:
                result += ipaddr
            else:
                result += '_' + ipaddr
    return result + '_' + db_net['pvc_id']


def _gen_object_update_data(obj, update_fields):
    data = {}
    for field in update_fields:
        data[field] = obj.get(field)
    result = json.dumps(data)
    if len(result) > constants.MAX_UPDATE_DATA_LENGTH:
        return None
    return result


def gen_network_update_data(net):
    return _gen_object_update_data(net, constants.NETWORK_UPDATE_FIELDS)


def gen_subnet_update_data(sub):
    return _gen_object_update_data(sub, constants.SUBNET_UPDATE_FIELDS)


def gen_port_update_data(port):
    return _gen_object_update_data(port, constants.PORT_UPDATE_FIELDS)


def _get_map_white_list():
    """
        Get pvc network white list. Easy to mock in a function.
    """
    return CONF.AGENT.map_powervc_networks


def network_has_subnet(net):
    """
        Check if a network has a subnet.  PowerVC networks that do not have
        a subnet are considerd DHCP networks.  We don't support DHCP
    """
    subnets = net.get('subnets')
    if not subnets or len(subnets) == 0:
        return False
    return True


def is_network_mappable(net):
    """
        Check if network can be sync
    """
    if 'provider:network_type' in net:
        network_type = net['provider:network_type']
        if network_type != 'vlan':
            return False
    if 'provider:physical_network' in net:
        physical_network = net['provider:physical_network']
        if physical_network != 'default':
            return False
    return True


def network_has_mappable_subnet(client, net):
    """
        Check if a network has mappable subnet, mappable subnet is defined in
        method is is_subnet_mappable()
    """
    subnets_id = net.get('subnets')
    if subnets_id:
        for sub_id in subnets_id:
            subnet = client.get_subnet(sub_id)
            if subnet and is_subnet_mappable(subnet):
                return True
    return False


def is_network_in_white_list(net):
    """
        Check if a network's name is in the white list.
    """
    whitelist = _get_map_white_list()
    if whitelist:
        """
          The following wildcards are allowed when
          the network name matches a pattern in the white list.
          (see the documentation for fnmatch):
          *        matches everything
          ?        matches any single character
          [seq]    matches any character in seq
          [!seq]   matches any character not in seq
        """
        for pat in whitelist:
            if pat == '*':
                return True
            elif net.get('name') and fnmatch.fnmatch(net.get('name'), pat):
                return True
        # No match found.
        return False
    else:
        # No network is allowed to sync.
        return False


def is_subnet_mappable(sub):
    if 'ip_version' in sub:
        if sub['ip_version'] == 6:
            return False
    if 'enable_dhcp' in sub:
        if sub['enable_dhcp']:
            return False
    return True


def is_port_mappable(port):
    fixed_ips = port.get('fixed_ips')
    if not fixed_ips:
        return False
    for ip in fixed_ips:
        ipaddr = ip.get('ip_address')
        if ipaddr and '.' in ipaddr:
            return True
    return False


def translate_net_id(db, net_id, target_os):
    if target_os == LOCAL_OS:
        db_net = db.get_network(pvc_id=net_id)
        if db_net:
            return db_net.get('local_id')
    else:
        db_net = db.get_network(local_id=net_id)
        if db_net:
            return db_net.get('pvc_id')
    return None


def translate_subnet_id(db, sub_id, target_os):
    if target_os == LOCAL_OS:
        db_sub = db.get_subnet(pvc_id=sub_id)
        if db_sub:
            return db_sub.get('local_id')
    else:
        db_sub = db.get_subnet(local_id=sub_id)
        if db_sub:
            return db_sub.get('pvc_id')
    return None


def translate_port_id(db, port_id, target_os):
    if target_os == LOCAL_OS:
        db_port = db.get_port(pvc_id=port_id)
        if db_port:
            return db_port.get('local_id')
    else:
        db_port = db.get_port(local_id=port_id)
        if db_port:
            return db_port.get('pvc_id')
    return None
