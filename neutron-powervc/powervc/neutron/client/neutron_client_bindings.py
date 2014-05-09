# Copyright 2013 IBM Corp.

"""
Module to contain all of the base Neutron client interfaces
"""

'''
Created on Aug 1, 2013

@author: John Kasperski
'''

from neutron.openstack.common import log as logging
from neutronclient.common import exceptions

import powervc.common.client.extensions.base as base
from powervc.common.constants import POWERVC_OS
from powervc.common.gettextutils import _
from powervc.neutron.common import constants
from powervc.neutron.common import utils
from powervc.neutron.db import powervc_db_v2

LOG = logging.getLogger(__name__)


class Client(base.ClientExtension):
    """Neutron Client access methods"""

    def __init__(self, client, os):
        super(Client, self).__init__(client)
        self.os = os
        self.db = powervc_db_v2.PowerVCAgentDB()
        self.client = client

    def _extact_event_payload(self, message):
        event = message.get('event_type')
        payload = message.get('payload')
        LOG.info(_("Handling AMQP message from %s: %s"), self.os, event)
        return (event, payload)

    def create_network(self, net):
        body = {}
        for field in constants.NETWORK_CREATE_FIELDS:
            if field in net:
                body[field] = net[field]
        request = {}
        request['network'] = body
        try:
            LOG.info(_("Create %s network: %s"), self.os, body)
            response = self.client.create_network(request)
            if response and 'network' in response:
                return response.get('network')
            return None
        except exceptions.NeutronClientException as e:
            LOG.exception(_("Error creating network: %s\nError message: %s"),
                          body, e)
            return None

    def create_subnet(self, sub):
        net_id = utils.translate_net_id(self.db, sub.get('network_id'),
                                        self.os)
        if not net_id:
            return None
        body = {}
        body['network_id'] = net_id
        for field in constants.SUBNET_CREATE_FIELDS:
            if field in sub:
                body[field] = sub[field]
        request = {}
        request['subnet'] = body
        try:
            LOG.info(_("Create %s subnet: %s"), self.os, body)
            response = self.client.create_subnet(request)
            if response and 'subnet' in response:
                return response.get('subnet')
            return None
        except exceptions.NeutronClientException as e:
            LOG.exception(_("Error creating subnet: %s\nError message: %s"),
                          body, e)
            return None

    def create_port(self, port):
        net_id = utils.translate_net_id(self.db, port.get('network_id'),
                                        self.os)
        if not net_id:
            return None
        body = {}
        body['network_id'] = net_id
        body['fixed_ips'] = []
        for field in constants.PORT_CREATE_FIELDS:
            if field in port:
                body[field] = port[field]
        if self.os == POWERVC_OS:
            body['device_owner'] = constants.POWERVC_DEVICE_OWNER
        elif port.get('device_id'):
            # If we are creating a local port and the PowerVC port has a
            # device id, then set the device id of the new local port to be
            # "pvc:" + PowerVC device id.
            body['device_id'] = constants.RSVD_PORT_PREFIX + port['device_id']
        fixed_ips = port.get('fixed_ips')
        if not fixed_ips:
            return None
        for ip in fixed_ips:
            ip_addr = ip.get('ip_address')
            if not ip_addr or ':' in ip_addr:
                continue
            sub_id = utils.translate_subnet_id(self.db, ip.get('subnet_id'),
                                               self.os)
            if not sub_id:
                LOG.warning(_("%s subnet does not exist for: %s"),
                            self.os, ip_addr)
                continue
            new_ip = {}
            new_ip['ip_address'] = ip_addr
            new_ip['subnet_id'] = sub_id
            body['fixed_ips'].append(new_ip)
        if len(body['fixed_ips']) == 0:
            return None
        request = {}
        request['port'] = body
        try:
            LOG.info(_("Create %s port: %s"), self.os, body)
            response = self.client.create_port(request)
            if response and 'port' in response:
                return response.get('port')
            return None
        except exceptions.NeutronClientException as e:
            LOG.exception(_("Error creating port: %s\nError message: %s"),
                          body, e)
            return None

    def delete_network(self, net_id):
        try:
            LOG.info(_("Delete %s network: %s"), self.os, net_id)
            return self.client.delete_network(net_id)
        except exceptions.NeutronClientException as e:
            LOG.exception(_("Error deleting network: %s"), e)
            return e

    def delete_subnet(self, sub_id):
        try:
            LOG.info(_("Delete %s subnet: %s"), self.os, sub_id)
            return self.client.delete_subnet(sub_id)
        except exceptions.NeutronClientException as e:
            LOG.exception(_("Error deleting subnet: %s"), e)
            return e

    def delete_port(self, port_id):
        try:
            LOG.info(_("Delete %s port: %s"), self.os, port_id)
            return self.client.delete_port(port_id)
        except exceptions.NeutronClientException as e:
            LOG.exception(_("Error deleting port: %s"), e)
            return e

    def get_networks(self):
        response = self.client.list_networks()
        if 'networks' in response:
            net_list = response['networks']
            networks = {}
            for net in net_list:
                if utils.is_network_mappable(net):
                    net_id = net['id']
                    networks[net_id] = net
            return networks
        return {}

    def get_subnets(self):
        response = self.client.list_subnets()
        if 'subnets' in response:
            sub_list = response['subnets']
            subnets = {}
            for sub in sub_list:
                if utils.is_subnet_mappable(sub):
                    sub_id = sub['id']
                    subnets[sub_id] = sub
            return subnets
        return {}

    def get_ports(self):
        response = self.client.list_ports()
        if 'ports' in response:
            port_list = response['ports']
            ports = {}
            for port in port_list:
                if utils.is_port_mappable(port):
                    port_id = port['id']
                    ports[port_id] = port
            return ports
        return {}

    def get_ports_on_network(self, net_id):
        response = self.client.list_ports(network_id=net_id)
        if 'ports' in response:
            return response['ports']
        return []

    def get_ports_on_subnet(self, net_id, subnet_id):
        port_list = self.get_ports_on_network(net_id)
        if len(port_list) == 0:
            return []
        ports = []
        for port in port_list:
            fixed_ips = port.get('fixed_ips')
            if not fixed_ips:
                continue
            for ip in fixed_ips:
                if ip.get('subnet_id') == subnet_id:
                    ports.append(port)
                    break
        return ports

    def get_network(self, net_id, log_error=False):
        try:
            response = self.client.show_network(net_id)
            if 'network' in response:
                return response['network']
            return None
        except exceptions.NeutronClientException as e:
            if log_error:
                LOG.exception(_("Error retrieving network: %s"), e)
            return None

    def get_subnet(self, sub_id, log_error=False):
        try:
            response = self.client.show_subnet(sub_id)
            if 'subnet' in response:
                return response['subnet']
            return None
        except exceptions.NeutronClientException as e:
            if log_error:
                LOG.exception(_("Error retrieving subnet: %s"), e)
            return None

    def get_port(self, port_id, log_error=False):
        try:
            response = self.client.show_port(port_id)
            if 'port' in response:
                return response['port']
            return None
        except exceptions.NeutronClientException as e:
            if log_error:
                LOG.exception(_("Error retrieving port: %s"), e)
            return None

    def set_port_device_id(self, port, device_id):
        body = {}
        body['device_id'] = device_id
        request = {}
        request['port'] = body
        try:
            LOG.info(_("Update %s port: %s"), self.os, body)
            return self.client.update_port(port['id'], request)
        except exceptions.NeutronClientException as e:
            LOG.exception(_("Error updating port: %s"), e)
            return None
        return None

    def update_network(self, net_dest, net_src):
        body = {}
        request = None
        for field in constants.NETWORK_UPDATE_FIELDS:
            if net_src[field] != net_dest[field]:
                body[field] = net_src[field]
                if not request:
                    request = {}
                    request['network'] = body
        if request:
            try:
                LOG.info(_("Update %s network: %s"), self.os, body)
                return self.client.update_network(net_dest['id'], request)
            except exceptions.NeutronClientException as e:
                LOG.exception(_("Error updating network: %s"), e)
                return None
        return None

    def update_subnet(self, sub_dest, sub_src):
        body = {}
        request = None
        for field in constants.SUBNET_UPDATE_FIELDS:
            if sub_src[field] != sub_dest[field]:
                body[field] = sub_src[field]
                if not request:
                    request = {}
                    request['subnet'] = body
        if request:
            try:
                LOG.info(_("Update %s subnet: %s"), self.os, body)
                return self.client.update_subnet(sub_dest['id'], request)
            except exceptions.NeutronClientException as e:
                LOG.exception(_("Error updating subnet: %s"), e)
                return None
        return None

    def update_port(self, port_dest, port_src):
        body = {}
        request = None
        for field in constants.PORT_UPDATE_FIELDS:
            if port_src[field] != port_dest[field]:
                body[field] = port_src[field]
                if not request:
                    request = {}
                    request['port'] = body
        if request:
            try:
                LOG.info(_("Update %s port: %s"), self.os, body)
                return self.client.update_port(port_dest['id'], request)
            except exceptions.NeutronClientException as e:
                LOG.exception(_("Error updating port: %s"), e)
                return None
        return None

    def get_ports_by_instance_uuid(self, ins_id):
        """
            Query all network ports by an instance id.
        """
        response = self.client.list_ports(device_id=ins_id)
        if 'ports' in response:
            return response['ports']
        return []
