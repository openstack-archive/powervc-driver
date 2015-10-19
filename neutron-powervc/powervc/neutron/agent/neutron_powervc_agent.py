# Copyright 2013 IBM Corp.

"""
Handles all of the Neutron logic necessary for PowerVC driver.

The :py:class:`PowerVCNeutronAgent` class is a Neutron agent.
"""

'''
Created on Jul 30, 2013

@author: John Kasperski
'''

import Queue
import threading
import os
import time
from exceptions import KeyboardInterrupt

from neutron.common import rpc
from oslo_log import log as logging

from oslo.config import cfg

from powervc.common.constants import LOCAL_OS
from powervc.common.constants import POWERVC_OS
from powervc.common.constants import PVC_TOPIC
from powervc.common.constants import SERVICE_TYPES
from powervc.common.client import factory
from powervc.common.gettextutils import _
from powervc.neutron.api import powervc_rpc
from powervc.neutron.client import local_os_bindings
from powervc.neutron.client import powervc_bindings
from powervc.neutron.common import constants
from powervc.neutron.common import utils
from powervc.neutron.db import powervc_db_v2

LOG = logging.getLogger(__name__)

agent_opts = [
    cfg.ListOpt('map_powervc_networks',
                default=['*'],
                help=_('List of <PowerVC network names> '
                       'to be mapped up to the local OS')),
    cfg.IntOpt('polling_interval',
               default=60,
               help=_("The number of seconds the agent will wait between "
                      "polling for network changes.")),
]

CONF = cfg.CONF
CONF.register_opts(agent_opts, "AGENT")


class PowerVCNeutronAgent(object):
    """
    This is the main PowerVC Neutron agent class
    """

    def __init__(self):
        self.end_thread = False
        self.polling_interval = CONF.AGENT.polling_interval
        self.retry_sync = time.time() + self.polling_interval
        self.db = powervc_db_v2.PowerVCAgentDB()
        self.event_q = Queue.Queue()
        self.handlers = {}
        self._register_handler(LOCAL_OS, constants.EVENT_NETWORK_CREATE,
                               self._handle_local_network_create)
        self._register_handler(LOCAL_OS, constants.EVENT_NETWORK_UPDATE,
                               self._handle_local_network_update)
        self._register_handler(LOCAL_OS, constants.EVENT_NETWORK_DELETE,
                               self._handle_local_network_delete)
        self._register_handler(LOCAL_OS, constants.EVENT_SUBNET_CREATE,
                               self._handle_local_subnet_create)
        self._register_handler(LOCAL_OS, constants.EVENT_SUBNET_UPDATE,
                               self._handle_local_subnet_update)
        self._register_handler(LOCAL_OS, constants.EVENT_SUBNET_DELETE,
                               self._handle_local_subnet_delete)
        self._register_handler(LOCAL_OS, constants.EVENT_PORT_CREATE,
                               self._handle_local_port_create)
        self._register_handler(LOCAL_OS, constants.EVENT_PORT_UPDATE,
                               self._handle_local_port_update)
        self._register_handler(LOCAL_OS, constants.EVENT_PORT_DELETE,
                               self._handle_local_port_delete)
        self._register_handler(POWERVC_OS, constants.EVENT_NETWORK_CREATE,
                               self._handle_pvc_network_create)
        self._register_handler(POWERVC_OS, constants.EVENT_NETWORK_UPDATE,
                               self._handle_pvc_network_update)
        self._register_handler(POWERVC_OS, constants.EVENT_NETWORK_DELETE,
                               self._handle_pvc_network_delete)
        self._register_handler(POWERVC_OS, constants.EVENT_SUBNET_CREATE,
                               self._handle_pvc_subnet_create)
        self._register_handler(POWERVC_OS, constants.EVENT_SUBNET_UPDATE,
                               self._handle_pvc_subnet_update)
        self._register_handler(POWERVC_OS, constants.EVENT_SUBNET_DELETE,
                               self._handle_pvc_subnet_delete)
        self._register_handler(POWERVC_OS, constants.EVENT_PORT_CREATE,
                               self._handle_pvc_port_create)
        self._register_handler(POWERVC_OS, constants.EVENT_PORT_UPDATE,
                               self._handle_pvc_port_update)
        self._register_handler(POWERVC_OS, constants.EVENT_PORT_DELETE,
                               self._handle_pvc_port_delete)
        self.pvc = powervc_bindings.Client(None, self)
        self.pvc = factory.POWERVC.new_client(str(SERVICE_TYPES.network),
                                              powervc_bindings.Client,
                                              self)
        self.local = local_os_bindings.Client(None, self)
        self.local = factory.LOCAL.new_client(str(SERVICE_TYPES.network),
                                              local_os_bindings.Client,
                                              self)
        self._setup_rpc()

    def _generate_db_stats(self):
        net_creating, net_active, net_deleting = self.db.get_network_stats()
        sub_creating, sub_active, sub_deleting = self.db.get_subnet_stats()
        port_creating, port_active, port_deleting = self.db.get_port_stats()
        stat_n = '{0:d}/{1:d}/{2:d}'.format(net_creating,
                                            net_active,
                                            net_deleting)
        stat_s = '{0:d}/{1:d}/{2:d}'.format(sub_creating,
                                            sub_active,
                                            sub_deleting)
        stat_p = '{0:d}/{1:d}/{2:d}'.format(port_creating,
                                            port_active,
                                            port_deleting)
        return '(n:{0}, s:{1}, p:{2})'.format(stat_n, stat_s, stat_p)

    def _handle_local_network_create(self, network):
        net_id = network.get('id')
        db_net = self.db.get_network(local_id=net_id)
        if db_net:
            LOG.info(_("DB entry for local network %s already exists"), net_id)
            return
        # verify that if local network has no subnet, not handle it.
        if not utils.network_has_subnet(network):
            # No subnet, but maybe one was created when this event was queued
            # up waiting to be processed.  Refresh with current network
            # that is actually on Local
            local_net = self.local.get_network(net_id)
            if not local_net:
                LOG.info(_("Local network %s might have been deleted"),
                         local_net.get('name'))
                return
            if not utils.network_has_subnet(local_net):
                LOG.info(_("Local network % has no subnet"),
                         local_net.get('name'))
                return
            if not utils.network_has_mappable_subnet(self.local, local_net):
                LOG.info(_("Local network % has no mappable subnet"),
                         local_net.get('name'))
                return

        sync_key = utils.gen_network_sync_key(network)
        db_net = self.db.get_network(sync_key=sync_key)
        if db_net:
            self.db.set_network_local_id(db_net, net_id)
        else:
            db_net = self.db.create_network(network, sync_key, local_id=net_id)
            new_net = self.pvc.create_network(network)
            if new_net:
                self.db.set_network_pvc_id(db_net, new_net.get('id'))

    def _handle_pvc_network_create(self, network):
        net_id = network.get('id')
        db_net = self.db.get_network(pvc_id=net_id)
        if db_net:
            LOG.info(_("DB entry for PowerVC network %s already exists"),
                     net_id)
            return
        # Verify that the PVC network has a subnet (most likely it won't)
        if not utils.network_has_subnet(network):
            # No subnet, but maybe one was created when this event was queued
            # up waiting to be processed.  Refresh with current network
            # that is actually on PowerVC
            network = self.pvc.get_network(net_id)
            if not network:
                LOG.warning(_("Unable to retrieve PowerVC network %s. "
                              "Network may have been deleted."), net_id)
                return
            # Check to see if the network has a subnet now (it might)
            if not utils.network_has_subnet(network):
                LOG.info(_("PowerVC network has no subnets: %s"),
                         network.get('name'))
                return
        sync_key = utils.gen_network_sync_key(network)
        db_net = self.db.get_network(sync_key=sync_key)
        if db_net:
            self.db.set_network_pvc_id(db_net, net_id)
        else:
            # Create at local only if the name is in the white list.
            if utils.is_network_in_white_list(network):
                db_net = self.db.create_network(network, sync_key,
                                                pvc_id=net_id)
                new_net = self.local.create_network(network)
                if new_net:
                    self.db.set_network_local_id(db_net, new_net.get('id'))
            else:
                LOG.info(_("PowerVC network is not allowed: %s"),
                         network.get('name'))

    def _handle_local_network_update(self, network):
        net_id = network.get('id')
        db_net = self.db.get_network(local_id=net_id)
        if not db_net:
            LOG.info(_("DB entry for local network %s does not exist"), net_id)
            return
        pvc_id = db_net.get('pvc_id')
        if not pvc_id:
            LOG.info(_("No PowerVC network for local network %s"), net_id)
            return
        pvc_net = self.pvc.get_network(pvc_id)
        if not pvc_net:
            LOG.warning(_("Unable to retrieve PowerVC network %s. "
                          "Network may have been deleted."), pvc_id)
            return
        if not utils.equal_networks(pvc_net, network):
            self.pvc.update_network(pvc_net, network)
            update_data = utils.gen_network_update_data(network)
            self.db.set_network_update_data(db_net, update_data)
        else:
            LOG.info(_("Network changes do not need to be updated"))

    def _handle_pvc_network_update(self, network):
        net_id = network.get('id')
        db_net = self.db.get_network(pvc_id=net_id)
        if not db_net:
            LOG.info(_("DB entry for PowerVC network %s does not exist"),
                     net_id)
            return
        local_id = db_net.get('local_id')
        if not local_id:
            LOG.info(_("No local network for PowerVC network %s"), net_id)
            return
        local_net = self.local.get_network(local_id)
        if not local_net:
            LOG.warning(_("Unable to retrieve local network %s. "
                          "Network may have been deleted."), local_id)
            return
        if not utils.equal_networks(local_net, network):
            self.local.update_network(local_net, network)
            update_data = utils.gen_network_update_data(network)
            self.db.set_network_update_data(db_net, update_data)
        else:
            LOG.info(_("Network changes do not need to be updated"))

    def _handle_local_network_delete(self, net_id):
        db_net = self.db.get_network(local_id=net_id)
        if not db_net:
            LOG.info(_("DB entry for local network %s does not exist"), net_id)
            return
        pvc_id = db_net.get('pvc_id')
        self.db.set_network_local_id(db_net, None)
        if pvc_id:
            port_list = self.pvc.get_ports_on_network(pvc_id)
            if len(port_list) > 0:
                LOG.info(_("Ports still defined on PowerVC network %s"),
                         pvc_id)
                return
            self.pvc.delete_network(pvc_id)
            network = self.pvc.get_network(pvc_id)
            if network:
                return
            self.db.delete_network(db_net)

    def _handle_pvc_network_delete(self, net_id):
        db_net = self.db.get_network(pvc_id=net_id)
        if not db_net:
            LOG.info(_("DB entry for PowerVC network %s does not exist"),
                     net_id)
            return
        local_id = db_net.get('local_id')
        self.db.set_network_pvc_id(db_net, None)
        if local_id:
            port_list = self.local.get_ports_on_network(local_id)
            if len(port_list) > 0:
                LOG.info(_("Ports still defined on local network %s"),
                         local_id)
                return
            self.local.delete_network(local_id)
            network = self.local.get_network(local_id)
            if network:
                return
            self.db.delete_network(db_net)

    def _handle_local_subnet_create(self, subnet):
        local_id = subnet.get('id')
        db_sub = self.db.get_subnet(local_id=local_id)
        if db_sub:
            LOG.info(_("DB entry for local subnet %s already exists"),
                     local_id)
            return
        net_id = subnet.get('network_id')
        db_net = self.db.get_network(local_id=net_id)
        if not db_net:
            # No database entry for the network. This may be the first subnet
            # created on the network -or- the network may be not "mappable".
            # Retrieve the network and pass it into the handler routine if
            # it is valid.
            network = self.local.get_network(net_id)
            if network and utils.is_network_mappable(network):
                self._handle_local_network_create(network)
            db_net = self.db.get_network(local_id=net_id)
            if not db_net:
                LOG.info(_("Unable to find DB entry for local network %s"),
                         net_id)
                return
        if db_net.get('status') == constants.STATUS_DELETING:
            LOG.info(_("Network %s is currently being deleted"), net_id)
            return
        sync_key = utils.gen_subnet_sync_key(subnet, db_net)
        db_sub = self.db.get_subnet(sync_key=sync_key)
        if db_sub:
            self.db.set_subnet_local_id(db_sub, local_id)
        else:
            db_sub = self.db.create_subnet(subnet, sync_key, local_id=local_id)
            new_sub = self.pvc.create_subnet(subnet)
            if new_sub:
                self.db.set_subnet_pvc_id(db_sub, new_sub.get('id'))

    def _handle_pvc_subnet_create(self, subnet):
        pvc_id = subnet.get('id')
        db_sub = self.db.get_subnet(pvc_id=pvc_id)
        if db_sub:
            LOG.info(_("DB entry for PowerVC subnet %s already exists"),
                     pvc_id)
            return
        net_id = subnet.get('network_id')
        db_net = self.db.get_network(pvc_id=net_id)
        if not db_net:
            # No database entry for the network. This may be the first subnet
            # created on the network -or- the network may be not "mappable".
            # Retrieve the network and pass it into the handler routine if
            # it is valid.
            pvc_net = self.pvc.get_network(net_id)
            if pvc_net and utils.is_network_mappable(pvc_net):
                self._handle_pvc_network_create(pvc_net)
            # Database entry for the network should exist now
            db_net = self.db.get_network(pvc_id=net_id)
            if not db_net:
                LOG.info(_("Unable to find DB entry for PowerVC network %s"),
                         net_id)
                return
        if db_net.get('status') == constants.STATUS_DELETING:
            LOG.info(_("Network %s is currently being deleted"), net_id)
            return
        sync_key = utils.gen_subnet_sync_key(subnet, db_net)
        db_sub = self.db.get_subnet(sync_key=sync_key)
        if db_sub:
            self.db.set_subnet_pvc_id(db_sub, pvc_id)
        else:
            db_sub = self.db.create_subnet(subnet, sync_key, pvc_id=pvc_id)
            new_sub = self.local.create_subnet(subnet)
            if new_sub:
                self.db.set_subnet_local_id(db_sub, new_sub.get('id'))

    def _handle_local_subnet_update(self, subnet):
        local_id = subnet.get('id')
        db_sub = self.db.get_subnet(local_id=local_id)
        if not db_sub:
            LOG.info(_("DB entry for local subnet %s does not exist"),
                     local_id)
            return
        pvc_id = db_sub.get('pvc_id')
        if not pvc_id:
            LOG.info(_("No PowerVC subnet for local subnet %s"), local_id)
            return
        pvc_sub = self.pvc.get_subnet(pvc_id)
        if not pvc_sub:
            LOG.warning(_("Unable to retrieve PowerVC subnet %s. "
                          "Subnet may have been deleted."), pvc_id)
            return
        if not utils.equal_subnets(pvc_sub, subnet):
            self.pvc.update_subnet(pvc_sub, subnet)
            update_data = utils.gen_subnet_update_data(subnet)
            self.db.set_subnet_update_data(db_sub, update_data)
        else:
            LOG.info(_("Subnet changes do not need to be updated"))

    def _handle_pvc_subnet_update(self, subnet):
        pvc_id = subnet.get('id')
        db_sub = self.db.get_subnet(pvc_id=pvc_id)
        if not db_sub:
            LOG.info(_("DB entry for PowerVC subnet %s does not exist"),
                     pvc_id)
            return
        local_id = db_sub.get('local_id')
        if not local_id:
            LOG.info(_("No local subnet for PowerVC subnet %s"), pvc_id)
            return
        local_sub = self.local.get_subnet(local_id)
        if not local_sub:
            LOG.warning(_("Unable to retrieve local subnet %s. "
                          "Subnet may have been deleted."), local_id)
            return
        if not utils.equal_subnets(local_sub, subnet):
            self.local.update_subnet(local_sub, subnet)
            update_data = utils.gen_subnet_update_data(subnet)
            self.db.set_subnet_update_data(db_sub, update_data)
        else:
            LOG.info(_("Subnet changes do not need to be updated"))

    def _handle_local_subnet_delete(self, sub_id):
        db_sub = self.db.get_subnet(local_id=sub_id)
        if not db_sub:
            LOG.info(_("DB entry for local subnet %s does not exist"), sub_id)
            return
        pvc_id = db_sub.get('pvc_id')
        self.db.set_subnet_local_id(db_sub, None)
        if not pvc_id:
            # Other half of database object has already been cleaned up
            return
        subnet = self.pvc.get_subnet(pvc_id)
        if not subnet:
            LOG.warning(_("Unable to retrieve PowerVC subnet %s. "
                          "Subnet may have been deleted."), pvc_id)
            self.db.delete_subnet(db_sub)
            return
        net_id = subnet.get('network_id')
        port_list = self.pvc.get_ports_on_subnet(net_id, pvc_id)
        if len(port_list) > 0:
            LOG.info(_("Ports still defined on PowerVC subnet %s"), pvc_id)
            return
        self.pvc.delete_subnet(pvc_id)
        subnet = self.pvc.get_subnet(pvc_id)
        if subnet:
            return
        self.db.delete_subnet(db_sub)

    def _handle_pvc_subnet_delete(self, sub_id):
        db_sub = self.db.get_subnet(pvc_id=sub_id)
        if not db_sub:
            LOG.info(_("DB entry for PowerVC subnet %s does not exist"),
                     sub_id)
            return
        local_id = db_sub.get('local_id')
        self.db.set_subnet_pvc_id(db_sub, None)
        if not local_id:
            # Other half of database object has already been cleaned up
            return
        subnet = self.local.get_subnet(local_id)
        if not subnet:
            LOG.warning(_("Unable to retrieve local subnet %s. "
                          "Subnet may have been deleted."), local_id)
            self.db.delete_subnet(db_sub)
            return
        net_id = subnet.get('network_id')
        port_list = self.local.get_ports_on_subnet(net_id, local_id)

        if len(port_list) > 0:
            if (self._ports_valid(port_list)):
                LOG.info(_("Ports still defined on local subnet %s"), local_id)
                return
        # no local ports left, delete the subnet
        self.local.delete_subnet(local_id)
        subnet = self.local.get_subnet(local_id)
        if subnet:
            return
        self.db.delete_subnet(db_sub)

    def _ports_valid(self, port_list):
        """
        Check if these ports are still valid
        :returns: True, if any of the ports is still valid;
                  False if none of them is valid.
        """
        # handle case:
        # local port is created and pvc port is not created;
        # local port status will be 'Creating', delete such port.
        deleted = 0
        for local_port in port_list:
            local_port_id = local_port.get('id')
            db_port = self.db.get_port(local_id=local_port_id)
            if db_port and db_port.get('status') == constants.STATUS_CREATING:
                # delete this local port
                self.local.delete_port(local_port_id)
                # if it is really deleted
                local_port = self.local.get_port(local_port_id)
                if not local_port:
                    self.db.delete_port(db_port)
                    deleted += 1
        # still some ports left there
        if (deleted != len(port_list)):
            return True
        # No port left
        return False

    def _handle_local_port_create(self, port):
        local_id = port.get('id')
        db_port = self.db.get_port(local_id=local_id)
        if db_port:
            LOG.info(_("DB entry for local port %s already exists"), local_id)
            return
        net_id = port.get('network_id')
        db_net = self.db.get_network(local_id=net_id)
        if not db_net:
            LOG.info(_("Unable to find DB entry for local network %s"), net_id)
            return
        if db_net.get('status') == constants.STATUS_DELETING:
            LOG.info(_("Network %s is currently being deleted"), net_id)
            return
        valid_subnet = False
        subnet_ids = utils.extract_subnets_from_port(port)
        for local_sub_id in subnet_ids:
            db_sub = self.db.get_subnet(local_id=local_sub_id)
            if db_sub:
                valid_subnet = True
                break
        if not valid_subnet:
            LOG.info(_("Unable to map local port %s. The subnet %s "
                       "is not mapped."), local_id, subnet_ids)
            return
        sync_key = utils.gen_port_sync_key(port, db_net)
        db_port = self.db.get_port(sync_key=sync_key)
        if db_port:
            self.db.set_port_local_id(db_port, local_id)
            return
        # Create the database entry for this new port
        db_port = self.db.create_port(port, sync_key, local_id=local_id)
        # Determine which instance owns this port
        device_id = port.get('device_id')
        # Determine if the instance is (HyperV / KVM) or PowerVC or Lock Port
        # if PowerVC, return.
        # If HyperV/KVM or Lock Port, reserve IP address in PowerVC
        if device_id == constants.POWERVC_LOCKDEVICE_ID\
                or not self.local.is_instance_on_power(device_id):
            # RTC 211682 - ip locked issue.
            # Nova booting a vm and neutron creating new port would race the port.
            # If the neutron creates the port before booting vm, 
            # the booting process would be failed as ip/port locked.
            time.sleep(15)
            try:
                new_port = self.pvc.create_port(port)
            except Exception, msg:
                LOG.warn(_("Try to create a port which has been used in booting vm. %s"), msg)
            # RTC 211682 - end
            if new_port:
                self.db.set_port_pvc_id(db_port, new_port.get('id'))

    def _handle_pvc_port_create(self, port):
        pvc_id = port.get('id')
        db_port = self.db.get_port(pvc_id=pvc_id)
        if db_port:
            LOG.info(_("DB entry for PowerVC port %s already exists"), pvc_id)
            return
        net_id = port.get('network_id')
        db_net = self.db.get_network(pvc_id=net_id)
        if not db_net:
            LOG.info(_("Unable to find DB entry for PowerVC network %s"),
                     net_id)
            return
        if db_net.get('status') == constants.STATUS_DELETING:
            LOG.info(_("Network %s is currently being deleted"), net_id)
            return
        valid_subnet = False
        subnet_ids = utils.extract_subnets_from_port(port)
        for pvc_sub_id in subnet_ids:
            db_sub = self.db.get_subnet(pvc_id=pvc_sub_id)
            if db_sub:
                valid_subnet = True
                break
        if not valid_subnet:
            LOG.info(_("Unable to map PowerVC port %s. The subnet %s "
                       "is not mapped."), pvc_id, subnet_ids)
            return
        sync_key = utils.gen_port_sync_key(port, db_net)
        db_port = self.db.get_port(sync_key=sync_key)
        if db_port:
            self.db.set_port_pvc_id(db_port, pvc_id)
            return
        db_port = self.db.create_port(port, sync_key, pvc_id=pvc_id)
        new_port = self.local.create_port(port)
        if new_port:
            self.db.set_port_local_id(db_port, new_port.get('id'))

    def _handle_local_port_update(self, port):
        local_id = port.get('id')
        db_port = self.db.get_port(local_id=local_id)
        if not db_port:
            LOG.info(_("DB entry for local port %s does not exist"), local_id)
            return
        pvc_id = db_port.get('pvc_id')
        if not pvc_id:
            LOG.info(_("No PowerVC port for local port %s"), local_id)
            return
        pvc_port = self.pvc.get_port(pvc_id)
        if not pvc_port:
            LOG.warning(_("Unable to retrieve PowerVC port %s. "
                          "Port may have been deleted."), pvc_id)
            return
        if not utils.equal_ports(pvc_port, port):
            self.pvc.update_port(pvc_port, port)
            update_data = utils.gen_port_update_data(port)
            self.db.set_port_update_data(db_port, update_data)
        else:
            LOG.info(_("Port changes do not need to be updated"))

    def _handle_pvc_port_update(self, port):
        pvc_id = port.get('id')
        db_port = self.db.get_port(pvc_id=pvc_id)
        if not db_port:
            LOG.info(_("DB entry for PowerVC port %s does not exist"), pvc_id)
            return
        local_id = db_port.get('local_id')
        if not local_id:
            LOG.info(_("No local port for PowerVC port %s"), pvc_id)
            return
        local_port = self.local.get_port(local_id)
        if not local_port:
            LOG.warning(_("Unable to retrieve local port %s. "
                          "Port may have been deleted."), local_id)
            return
        if not utils.equal_ports(local_port, port):
            self.local.update_port(local_port, port)
            update_data = utils.gen_port_update_data(port)
            self.db.set_port_update_data(db_port, update_data)
        else:
            LOG.info(_("Port changes do not need to be updated"))

    def _handle_local_port_delete(self, port_id):
        db_port = self.db.get_port(local_id=port_id)
        if not db_port:
            LOG.info(_("DB entry for local port %s does not exist"), port_id)
            return
        pvc_id = db_port.get('pvc_id')
        self.db.set_port_local_id(db_port, None)
        if not pvc_id:
            # Other half of database object has already been cleaned up
            return
        pvc_port = self.pvc.get_port(pvc_id)
        if not pvc_port:
            LOG.warning(_("Unable to retrieve PowerVC port %s. "
                          "Port may have been deleted."), pvc_id)
            self.db.delete_port(db_port)
            return
        device_id = pvc_port.get('device_id')
        if device_id and len(device_id) > 0\
                and device_id != constants.POWERVC_LOCKDEVICE_ID:
            LOG.info(_("PowerVC port %s can not be deleted. Port is in-use "
                       "by VM %s."), pvc_id, device_id)
            LOG.info(_("Recreate the local port to prevent this IP "
                       "address from being used by another instance."))
            new_port = self.local.create_port(pvc_port)
            if new_port:
                # Update the database entry with new port uuid
                self.db.set_port_local_id(db_port, new_port.get('id'))
            return
        self.pvc.delete_port(pvc_id)
        pvc_port = self.pvc.get_port(pvc_id)
        if pvc_port:
            return
        self.db.delete_port(db_port)

    def _handle_pvc_port_delete(self, port_id):
        db_port = self.db.get_port(pvc_id=port_id)
        if not db_port:
            LOG.info(_("DB entry for PowerVC port %s does not exist"), port_id)
            return
        local_id = db_port.get('local_id')
        self.db.set_port_pvc_id(db_port, None)
        if not local_id:
            # Other half of database object has already been cleaned up
            return
        local_port = self.local.get_port(local_id)
        if not local_port:
            LOG.warning(_("Unable to retrieve local port %s. "
                          "Port may have been deleted."), local_id)
            self.db.delete_port(db_port)
            return
        self._delete_local_port(local_port, db_port)

    def _delete_local_port(self, local_port, db_port):
        # complex logic here on how to handle it
        # some possible cases for this local port:
        # 1) device_id = Lock occurs when lock IP address done.
        # Delete the local port
        # 2) device_owner = network:router_interface  (see issue 173350).
        # re-create the PVC port
        # 3) device_id = instance that no longer exists.
        # Delete the local port
        # 4) device_id = HyperV/KVM instance.
        # Re-create the PVC port
        # 5) device_id = PowerVC deployed instance.
        # Delete the local port
        #
        local_id = db_port.get('local_id')
        # case 2
        device_owner = local_port.get('device_owner')
        if device_owner and (device_owner == "network:router_interface"):
            LOG.info(_("Local port %s can not be deleted. Port is in-use "
                       "by device_owner %s."), local_id, device_owner)
            new_port = self.pvc.create_port(local_port)
            if new_port:
                self.db.set_port_pvc_id(db_port, new_port.get('id'))
            return

        device_id = local_port.get('device_id')
        if device_id and self.local.is_instance_valid(device_id):
            if not self.local.is_instance_on_power(device_id):
                # case 4)
                LOG.info(_("Local port %s can not be deleted. Port is in-use "
                           "by VM %s."), local_id, device_id)
                new_port = self.pvc.create_port(local_port)
                if new_port:
                    self.db.set_port_pvc_id(db_port, new_port.get('id'))
                return
        # for case 1) 3) 5)
        self.local.delete_port(local_id)
        local_port = self.local.get_port(local_id)
        if local_port:
            return
        self.db.delete_port(db_port)

    def _register_handler(self, event_os, event_type, handler):
        key = event_type
        if event_os:
            key = event_os + ':' + event_type
        self.handlers[key] = handler

    def _handle_event(self, event):
        event_os = event.get(constants.EVENT_OS)
        event_type = event.get(constants.EVENT_TYPE)
        event_obj = event.get(constants.EVENT_OBJECT)
        if event_type == constants.EVENT_END_THREAD:
            return
        elif event_type == constants.EVENT_FULL_SYNC:
            self._synchronize(event_os)
            return
        key = event_type
        if event_os:
            key = event_os + ':' + event_type
        handler = self.handlers.get(key)
        if not handler:
            LOG.error(_("No handler found for: %s"), key)
            return
        return handler(event_obj)

    def queue_event(self, event_os, event_type, event_obj):
        event = {}
        event[constants.EVENT_OS] = event_os
        event[constants.EVENT_TYPE] = event_type
        event[constants.EVENT_OBJECT] = event_obj
        self.event_q.put(event)

    def _setup_rpc(self):
        """
        set up RPC support
        """
        from powervc.common import config
        rpc.init(config.AMQP_OPENSTACK_CONF)
        self.topic = PVC_TOPIC
        self.conn = rpc.create_connection(new=True)
        self.endpoints = [powervc_rpc.PVCRpcCallbacks(self)]
        self.conn.create_consumer(self.topic, self.endpoints, fanout=False)
        self.conn.consume_in_threads()
        LOG.info(_("RPC listener created"))

    def _synchronize(self, default_target=LOCAL_OS):
        """
        Main synchronize routine
        """
        start = time.time()
        LOG.info(_("Synchronizing all networks/subnets/ports..."))
        self._synchronize_networks(default_target)
        self._synchronize_subnets(default_target)
        self._synchronize_ports(default_target)
        db_stats = self._generate_db_stats()
        end = time.time()
        elapsed = '{0:.4} seconds'.format(end - start)
        LOG.info(_("Full sync elapsed time: %s %s"), elapsed, db_stats)
        self.retry_sync = time.time() + self.polling_interval

    def _synchronize_networks(self, target=LOCAL_OS):
        pvc_nets = self.pvc.get_networks()
        local_nets = self.local.get_networks()
        self._sync_deleted_nets(pvc_nets, local_nets)
        self._sync_new_pvc_nets(pvc_nets)
        self._sync_new_local_nets(local_nets)
        self._sync_updated_nets(pvc_nets, local_nets, target)
        self._sync_deleting_nets()
        self._sync_creating_nets(pvc_nets, local_nets)

    def _sync_deleted_nets(self, pvc_nets, local_nets):
        db_networks = self.db.get_networks()
        for db_net in db_networks:
            pvc_id, local_id = utils.extract_ids_from_entry(db_net)
            if pvc_id and pvc_id not in pvc_nets.keys():
                self.db.set_network_pvc_id(db_net, None)
            if local_id and local_id not in local_nets.keys():
                self.db.set_network_local_id(db_net, None)

    def _sync_new_pvc_nets(self, pvc_nets):
        for pvc_net in pvc_nets.values():
            pvc_id = pvc_net.get('id')
            db_net = self.db.get_network(pvc_id=pvc_id)
            if db_net:
                # DB entry for this PVC network already exists
                continue
            # Verify that the PVC network has a subnet. A network without
            # a subnet is considered a DHCP network by PowerVC.  We do not
            # support DHCP networks
            if not utils.network_has_subnet(pvc_net):
                LOG.info(_("PowerVC network has no subnets: %s"),
                         pvc_net.get('name'))
                continue
            sync_key = utils.gen_network_sync_key(pvc_net)
            db_net = self.db.get_network(sync_key=sync_key)
            if db_net:
                self.db.set_network_pvc_id(db_net, pvc_id)
            else:
                # Check if the pvc network is allowed to sync.
                if utils.is_network_in_white_list(pvc_net):
                    self.db.create_network(pvc_net, sync_key, pvc_id=pvc_id)
                else:
                    LOG.info(_("PowerVC network is not allowed: %s"),
                             pvc_net.get('name'))

    def _sync_new_local_nets(self, local_nets):
        for local_net in local_nets.values():
            local_id = local_net.get('id')
            db_net = self.db.get_network(local_id=local_id)
            if db_net:
                # DB entry for this local network already exists
                continue
            # if local network has no subnet, not handle it.
            if not utils.network_has_subnet(local_net):
                LOG.info(_("Local network %s has no subnet"),
                         local_net.get('name'))
                continue
            # if local network has subnet, verify if the subnet is mappable
            if not utils.network_has_mappable_subnet(self.local,
                                                     local_net):
                LOG.info(_("Local network %s has no mappable subnet"),
                         local_net.get('name'))
                continue
            sync_key = utils.gen_network_sync_key(local_net)
            db_net = self.db.get_network(sync_key=sync_key)
            if db_net:
                self.db.set_network_local_id(db_net, local_id)
            else:
                self.db.create_network(local_net, sync_key, local_id=local_id)

    def _sync_updated_nets(self, pvc_nets, local_nets, target):
        db_active_list = self.db.get_networks(constants.STATUS_ACTIVE)
        for db_net in db_active_list:
            pvc_id, local_id = utils.extract_ids_from_entry(db_net)
            pvc_net = pvc_nets.get(pvc_id)
            local_net = local_nets.get(local_id)
            result = utils.compare_networks(local_net, pvc_net, db_net, target)
            if result:
                if result == LOCAL_OS:
                    self.local.update_network(local_net, pvc_net)
                    update_data = utils.gen_network_update_data(pvc_net)
                else:
                    self.pvc.update_network(pvc_net, local_net)
                    update_data = utils.gen_network_update_data(local_net)
                self.db.set_network_update_data(db_net, update_data)

    def _sync_deleting_nets(self):
        db_delete_list = self.db.get_networks(constants.STATUS_DELETING)
        for db_net in db_delete_list:
            pvc_id, local_id = utils.extract_ids_from_entry(db_net)
            if pvc_id and local_id:
                self.db.fix_incorrect_state(db_net)
                continue
            if pvc_id:
                pvc_ports = self.pvc.get_ports_on_network(pvc_id)
                if len(pvc_ports) > 0:
                    LOG.info(_("Ports are still defined on PowerVC network "
                               "%s. Network can not be deleted."), pvc_id)
                    continue
                self.pvc.delete_network(pvc_id)
                pvc_net = self.pvc.get_network(pvc_id)
                if pvc_net:
                    continue
            if local_id:
                local_ports = self.local.get_ports_on_network(local_id)
                if len(local_ports) > 0:
                    LOG.info(_("Ports are still defined on local network "
                               "%s. Network can not be deleted."), local_id)
                    continue
                self.local.delete_network(local_id)
                local_net = self.local.get_network(local_id)
                if local_net:
                    continue
            self.db.delete_network(db_net)

    def _sync_creating_nets(self, pvc_nets, local_nets):
        db_create_list = self.db.get_networks(constants.STATUS_CREATING)
        for db_net in db_create_list:
            pvc_id, local_id = utils.extract_ids_from_entry(db_net)
            if pvc_id:
                pvc_net = pvc_nets.get(pvc_id)
                local_net = self.local.create_network(pvc_net)
                if local_net:
                    local_id = local_net.get('id')
                    self.db.set_network_local_id(db_net, local_id)
                continue
            if local_id:
                local_net = local_nets.get(local_id)
                pvc_net = self.pvc.create_network(local_net)
                if pvc_net:
                    pvc_id = pvc_net.get('id')
                    self.db.set_network_pvc_id(db_net, pvc_id)
                continue

    def _synchronize_subnets(self, target=LOCAL_OS):
        pvc_subnets = self.pvc.get_subnets()
        local_subnets = self.local.get_subnets()
        self._sync_deleted_subnets(pvc_subnets, local_subnets)
        self._sync_new_pvc_subnets(pvc_subnets)
        self._sync_new_local_subnets(local_subnets)
        self._sync_updated_subnets(pvc_subnets, local_subnets, target)
        self._sync_deleting_subnets(pvc_subnets, local_subnets)
        self._sync_creating_subnets(pvc_subnets, local_subnets)

    def _sync_deleted_subnets(self, pvc_subnets, local_subnets):
        db_subnets = self.db.get_subnets()
        for db_sub in db_subnets:
            pvc_id, local_id = utils.extract_ids_from_entry(db_sub)
            if pvc_id and pvc_id not in pvc_subnets.keys():
                self.db.set_subnet_pvc_id(db_sub, None)
            if local_id and local_id not in local_subnets.keys():
                self.db.set_subnet_local_id(db_sub, None)

    def _sync_new_pvc_subnets(self, pvc_subnets):
        for pvc_sub in pvc_subnets.values():
            pvc_id = pvc_sub.get('id')
            db_sub = self.db.get_subnet(pvc_id=pvc_id)
            if db_sub:
                # DB entry for this PVC subnet already exists
                continue
            pvc_net_id = pvc_sub.get('network_id')
            db_net = self.db.get_network(pvc_id=pvc_net_id)
            if not db_net:
                # Subnet is associated with a network that is not mapped
                continue
            if db_net.get('status') == constants.STATUS_DELETING:
                # Do not create new subnet if network is being deleted
                continue
            sync_key = utils.gen_subnet_sync_key(pvc_sub, db_net)
            db_sub = self.db.get_subnet(sync_key=sync_key)
            if db_sub:
                self.db.set_subnet_pvc_id(db_sub, pvc_id)
            else:
                self.db.create_subnet(pvc_sub, sync_key, pvc_id=pvc_id)

    def _sync_new_local_subnets(self, local_subnets):
        for local_sub in local_subnets.values():
            local_id = local_sub.get('id')
            db_sub = self.db.get_subnet(local_id=local_id)
            if db_sub:
                # DB entry for this local subnet already exists
                continue
            local_net_id = local_sub.get('network_id')
            db_net = self.db.get_network(local_id=local_net_id)
            if not db_net:
                # Subnet is associated with a network that is not mapped
                continue
            if db_net.get('status') == constants.STATUS_DELETING:
                # Do not create new subnet if network is being deleted
                continue
            sync_key = utils.gen_subnet_sync_key(local_sub, db_net)
            db_sub = self.db.get_subnet(sync_key=sync_key)
            if db_sub:
                self.db.set_subnet_local_id(db_sub, local_id)
            else:
                self.db.create_subnet(local_sub, sync_key, local_id=local_id)

    def _sync_updated_subnets(self, pvc_subnets, local_subnets, target):
        db_active_list = self.db.get_subnets(constants.STATUS_ACTIVE)
        for db_sub in db_active_list:
            pvc_id, local_id = utils.extract_ids_from_entry(db_sub)
            pvc_sub = pvc_subnets.get(pvc_id)
            local_sub = local_subnets.get(local_id)
            result = utils.compare_subnets(local_sub, pvc_sub, db_sub, target)
            if result:
                if result == LOCAL_OS:
                    self.local.update_subnet(local_sub, pvc_sub)
                    update_data = utils.gen_subnet_update_data(pvc_sub)
                else:
                    self.pvc.update_subnet(pvc_sub, local_sub)
                    update_data = utils.gen_subnet_update_data(local_sub)
                self.db.set_subnet_update_data(db_sub, update_data)

    def _sync_deleting_subnets(self, pvc_subnets, local_subnets):
        db_delete_list = self.db.get_subnets(constants.STATUS_DELETING)
        for db_sub in db_delete_list:
            pvc_id, local_id = utils.extract_ids_from_entry(db_sub)
            if pvc_id and local_id:
                self.db.fix_incorrect_state(db_sub)
                continue
            if pvc_id:
                pvc_sub = pvc_subnets.get(pvc_id)
                pvc_net_id = pvc_sub.get('network_id')
                pvc_ports = self.pvc.get_ports_on_subnet(pvc_net_id,
                                                         pvc_id)
                if len(pvc_ports) > 0:
                    LOG.info(_("Ports are still defined on PowerVC subnet "
                               "%s. Subnet can not be deleted."), pvc_id)
                    continue
                self.pvc.delete_subnet(pvc_id)
                pvc_sub = self.pvc.get_subnet(pvc_id)
                if pvc_sub:
                    continue
            if local_id:
                local_sub = local_subnets.get(local_id)
                local_net_id = local_sub.get('network_id')
                local_ports = self.local.get_ports_on_subnet(local_net_id,
                                                             local_id)
                if len(local_ports) > 0:
                    if (self._ports_valid(local_ports)):
                        LOG.info(_("Ports are still defined on local OS"
                                   " subnet %s. Subnet can not be deleted."),
                                 local_id)
                        continue
                self.local.delete_subnet(local_id)
                local_sub = self.local.get_subnet(local_id)
                if local_sub:
                    continue
            self.db.delete_subnet(db_sub)

    def _sync_creating_subnets(self, pvc_subnets, local_subnets):
        db_create_list = self.db.get_subnets(constants.STATUS_CREATING)
        for db_sub in db_create_list:
            pvc_id, local_id = utils.extract_ids_from_entry(db_sub)
            if pvc_id:
                pvc_sub = pvc_subnets.get(pvc_id)
                local_sub = self.local.create_subnet(pvc_sub)
                if local_sub:
                    local_id = local_sub.get('id')
                    self.db.set_subnet_local_id(db_sub, local_id)
                continue
            if local_id:
                local_sub = local_subnets.get(local_id)
                pvc_sub = self.pvc.create_subnet(local_sub)
                if pvc_sub:
                    pvc_id = pvc_sub.get('id')
                    self.db.set_subnet_pvc_id(db_sub, pvc_id)
                continue

    def _synchronize_ports(self, target=LOCAL_OS):
        pvc_ports = self.pvc.get_ports()
        local_ports = self.local.get_ports()
        self._sync_deleted_ports(pvc_ports, local_ports)
        self._sync_new_pvc_ports(pvc_ports)
        self._sync_new_local_ports(local_ports)
        self._sync_updated_ports(pvc_ports, local_ports, target)
        self._sync_deleting_ports()
        self._sync_creating_ports(pvc_ports, local_ports)

    def _sync_deleted_ports(self, pvc_ports, local_ports):
        db_ports = self.db.get_ports()
        for db_port in db_ports:
            pvc_id, local_id = utils.extract_ids_from_entry(db_port)
            if pvc_id and pvc_id not in pvc_ports.keys():
                self.db.set_port_pvc_id(db_port, None)
            if local_id and local_id not in local_ports.keys():
                self.db.set_port_local_id(db_port, None)

    def _sync_new_pvc_ports(self, pvc_ports):
        for pvc_port in pvc_ports.values():
            pvc_id = pvc_port.get('id')
            db_port = self.db.get_port(pvc_id=pvc_id)
            if db_port:
                # DB entry for this PVC port already exists
                continue
            pvc_net_id = pvc_port.get('network_id')
            db_net = self.db.get_network(pvc_id=pvc_net_id)
            if not db_net:
                # Port is associated with a network that is not mapped
                continue
            if db_net.get('status') == constants.STATUS_DELETING:
                # Do not create new port if network is being deleted
                continue
            valid_subnet = False
            subnet_ids = utils.extract_subnets_from_port(pvc_port)
            for pvc_sub_id in subnet_ids:
                db_sub = self.db.get_subnet(pvc_id=pvc_sub_id)
                if db_sub:
                    valid_subnet = True
                    break
            if not valid_subnet:
                LOG.info(_("Unable to map PowerVC port %s. The subnet %s "
                           "is not mapped."), pvc_id, subnet_ids)
                continue
            sync_key = utils.gen_port_sync_key(pvc_port, db_net)
            db_port = self.db.get_port(sync_key=sync_key)
            if db_port:
                self.db.set_port_pvc_id(db_port, pvc_id)
            else:
                self.db.create_port(pvc_port, sync_key, pvc_id=pvc_id)

    def _sync_new_local_ports(self, local_ports):
        for local_port in local_ports.values():
            local_id = local_port.get('id')
            db_port = self.db.get_port(local_id=local_id)
            if db_port:
                # DB entry for this local port already exists
                continue
            local_net_id = local_port.get('network_id')
            db_net = self.db.get_network(local_id=local_net_id)
            if not db_net:
                # Port is associated with a network that is not mapped
                continue
            if db_net.get('status') == constants.STATUS_DELETING:
                # Do not create new port if network is being deleted
                continue
            if not db_net.get('pvc_id'):
                # The PowerVC network no longer exists
                continue
            valid_subnet = False
            subnet_ids = utils.extract_subnets_from_port(local_port)
            for local_sub_id in subnet_ids:
                db_sub = self.db.get_subnet(local_id=local_sub_id)
                if db_sub:
                    valid_subnet = True
                    break
            if not valid_subnet:
                LOG.info(_("Unable to map local port %s. The subnet %s "
                           "is not mapped."), local_id, subnet_ids)
                continue
            sync_key = utils.gen_port_sync_key(local_port, db_net)
            db_port = self.db.get_port(sync_key=sync_key)
            if db_port:
                self.db.set_port_local_id(db_port, local_id)
            else:
                self.db.create_port(local_port, sync_key, local_id=local_id)

    def _sync_updated_ports(self, pvc_ports, local_ports, target):
        db_active_list = self.db.get_ports(constants.STATUS_ACTIVE)
        vm_map = None
        for db_port in db_active_list:
            pvc_id, local_id = utils.extract_ids_from_entry(db_port)
            pvc_port = pvc_ports.get(pvc_id)
            local_port = local_ports.get(local_id)
            if not pvc_port or not local_port:
                continue
            # Fix up device id in local port (if necessary)
            pvc_device = pvc_port.get('device_id')
            local_device = local_port.get('device_id')
            if (not local_device or len(local_device) == 0 or
                    local_device.startswith(constants.RSVD_PORT_PREFIX)):
                if pvc_device and len(pvc_device) > 0:
                    if vm_map is None:
                        LOG.info(_("Retrieving PowerVC to local VM mappings"))
                        vm_map = self.local.get_power_vm_mapping()
                    if pvc_device in vm_map:
                        local_device_id = vm_map[pvc_device]
                        LOG.info(_("Update local port %s with device id %s"),
                                 local_id, local_device_id)
                        self.local.set_port_device_id(local_port,
                                                      local_device_id)
                    elif pvc_device == constants.POWERVC_LOCKDEVICE_ID:
                        LOG.debug(_("Lock port, skip updating local port: %s"),
                                 local_id)
                    else:
                        LOG.warning(_("Unable to update local port %s. Local "
                                   "instance for PowerVC %s can not be found"),
                                 local_id, pvc_device)
            # Do any of the other fields in the ports need to be updated
            result = utils.compare_ports(local_port, pvc_port, db_port, target)
            if result:
                if result == LOCAL_OS:
                    self.local.update_port(local_port, pvc_port)
                    update_data = utils.gen_port_update_data(pvc_port)
                else:
                    self.pvc.update_port(pvc_port, local_port)
                    update_data = utils.gen_port_update_data(local_port)
                self.db.set_port_update_data(db_port, update_data)

    def _sync_deleting_ports(self):
        db_delete_list = self.db.get_ports(constants.STATUS_DELETING)
        for db_port in db_delete_list:
            pvc_id, local_id = utils.extract_ids_from_entry(db_port)
            if pvc_id and local_id:
                self.db.fix_incorrect_state(db_port)
                continue
            if pvc_id:
                pvc_port = self.pvc.get_port(pvc_id)
                if not pvc_port:
                    self.db.delete_port(db_port)
                    continue
                device_id = pvc_port.get('device_id')
                if device_id and len(device_id) > 0\
                        and device_id != constants.POWERVC_LOCKDEVICE_ID:
                    LOG.info(_("PVC port %s can not be deleted. Port is "
                               "in-use by VM %s."), pvc_id, device_id)
                    LOG.info(_("Recreate the local port to prevent this IP "
                               "address from being used by another instance."))
                    new_port = self.local.create_port(pvc_port)
                    if new_port:
                        # Update the database entry with new port uuid
                        self.db.set_port_local_id(db_port, new_port.get('id'))
                    continue
                self.pvc.delete_port(pvc_id)
                pvc_port = self.pvc.get_port(pvc_id)
                if pvc_port:
                    continue
                self.db.delete_port(db_port)
            if local_id:
                local_port = self.local.get_port(local_id)
                if not local_port:
                    self.db.delete_port(db_port)
                    continue
                self._delete_local_port(local_port, db_port)
                continue

    def _sync_creating_ports(self, pvc_ports, local_ports):
        db_create_list = self.db.get_ports(constants.STATUS_CREATING)
        for db_port in db_create_list:
            pvc_id, local_id = utils.extract_ids_from_entry(db_port)
            if pvc_id:
                pvc_port = pvc_ports.get(pvc_id)
                local_port = self.local.create_port(pvc_port)
                if local_port:
                    local_id = local_port.get('id')
                    self.db.set_port_local_id(db_port, local_id)
                continue
            if local_id:
                local_port = local_ports.get(local_id)
                # Determine which instance owns this port
                device_id = local_port.get('device_id')
                if device_id == constants.POWERVC_LOCKDEVICE_ID\
                        or not self.local.is_instance_on_power(device_id):
                    # Create a port on PVC if this is a local instance,
                    # so PVC won't use its IP address.
                    pvc_port = self.pvc.create_port(local_port)
                    if pvc_port:
                        pvc_id = pvc_port.get('id')
                        self.db.set_port_pvc_id(db_port, pvc_id)
                continue

    def set_device_id_on_port_by_pvc_instance_uuid(self,
                                                   db_api,
                                                   device_id,
                                                   pvc_ins_uuid):
        """
        Query the ports by pvc instance uuid, and set its
        local instance id(device_id).
        """
        local_ids = []
        pvc_ports = self.pvc.get_ports_by_instance_uuid(pvc_ins_uuid)
        if pvc_ports and len(pvc_ports) > 0:
            for pvc_port in pvc_ports:
                pvc_id = pvc_port.get('id')
                # Can't use self.db because of thread sync. issue,
                # so passed in one from the caller.
                db_port = db_api.get_port(pvc_id=pvc_id)
                if not db_port:
                    LOG.debug(_("No db_port found: %s"), pvc_id)
                    continue
                local_id = db_port.get('local_id')
                if not local_id:
                    LOG.debug(_("No local_port_id found: %s"), pvc_id)
                    continue
                local_port = self.local.get_port(local_id)
                if not local_port:
                    LOG.debug(_("No local_port found: %s"), pvc_id)
                    continue
                self.local.set_port_device_id(local_port, device_id)
                local_ids.append(local_id)
                LOG.debug(_("Set device_id for %s with %s"), pvc_id, device_id)
        return local_ids

    def _process_event_queue(self):
        """
        Main loop for the agent
        """
        while not self.end_thread:
            try:
                # Perform a full synchronization of all neutron objects
                self._synchronize()
            except Exception as e:
                LOG.exception(_("Error during synchronize: %s"), e)
                # We don't want to kill the agent on a sync-error. Continue
                # running and retry the operation when the polling interval
                # wait_time time has elapsed.
                self.retry_sync = time.time() + self.polling_interval
                pass

            # Process events while waiting the polling interval
            while (time.time() < self.retry_sync or not self.event_q.empty()):
                event = None
                try:
                    wait = self.retry_sync - time.time()
                    if wait <= 0:
                        wait = 1
                    event = self.event_q.get(True, wait)
                except Queue.Empty:
                    LOG.info(_("No events posted"))
                    pass
                except Exception as e:
                    LOG.exception(_("Error while waiting for event: %s"), e)
                    return
                if self.end_thread:
                    LOG.info(_("Event thread signaled to end"))
                    return
                if event:
                    try:
                        self.event_q.task_done()
                        LOG.info(_("Event received: %s"), event)
                        self._handle_event(event)
                    except Exception as e:
                        LOG.exception(_("Error handling event: %s"), e)
                        # We don't want to kill the agent if an error occurs
                        # handling an event
                        pass

    def daemon_loop(self):
        # Start a thread here to process the event queue. If the event queue
        # is called from the main thread, incoming RPC requests are delayed
        # until the full sync is done. We could have dropped the event queue
        # wait time and added a small sleep() to the Queue.Empty exception,
        # but this would cause RPC events to be delayed until this occurs.
        t = threading.Thread(target=self._process_event_queue)
        t.setDaemon(True)
        t.start()

        # While the worker thread is alive, sleep
        while t.isAlive():
            try:
                time.sleep(self.polling_interval)
            except KeyboardInterrupt:
                LOG.info(_("Waiting for worker thread to end"))
                self.end_thread = True
                event = {}
                event[constants.EVENT_TYPE] = constants.EVENT_END_THREAD
                self.event_q.put(event)
                t.join(self.polling_interval)
        LOG.info(_("Worker thread is dead.  Exiting"))


def main():
    try:
        LOG.info(_("-" * 80))
        LOG.info(_("Agent initializing... "))
        agent = PowerVCNeutronAgent()

        # Start everything.
        LOG.info(_("Agent running... "))
        agent.daemon_loop()

    except Exception as e:
        LOG.exception(_("Exception occurred in agent: %s"), e)

    finally:
        # Use hard exit here so that QPID threads will be killed
        LOG.info(_("Agent exiting..."))
        os._exit(os.EX_OK)
