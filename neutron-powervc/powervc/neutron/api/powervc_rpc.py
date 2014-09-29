# Copyright 2013 IBM Corp.

from neutron.openstack.common import log as logging

from powervc.common.constants import LOCAL_OS
from powervc.common.constants import POWERVC_OS
from powervc.common.gettextutils import _
from powervc.neutron.common import utils
from powervc.neutron.db import powervc_db_v2

import time

LOG = logging.getLogger(__name__)


# RPC callback
class PVCRpcCallbacks(object):
    """
    RPC callbacks for nova driver calling this agent.
    MUST set topic=powervc at both sides.
    """

    # Set RPC API version to 1.0 by default.
    RPC_API_VERSION = '1.0'

    def __init__(self, neutron_agent):

        super(PVCRpcCallbacks, self).__init__()
        self.agent = neutron_agent
        self.db = powervc_db_v2.PowerVCAgentDB()

    def get_local_network_uuid(self, context, network_id):
        LOG.info(_("Neutron Agent RPC: get_local_network_uuid:"))
        LOG.info(_("- pvc_net_id: %s"), network_id)
        local_net_id = utils.translate_net_id(self.db, network_id, LOCAL_OS)
        LOG.info(_("- local_net_id: %s"), local_net_id)
        return local_net_id

    def get_pvc_network_uuid(self, context, network_id):
        LOG.info(_("Neutron Agent RPC: get_pvc_network_uuid:"))
        LOG.info(_("- local_net_id: %s"), network_id)
        pvc_net_id = utils.translate_net_id(self.db, network_id, POWERVC_OS)
        LOG.info(_("- pvc_net_id: %s"), pvc_net_id)
        return pvc_net_id

    def get_pvc_port_uuid(self, context, port_id):
        LOG.info(_("Neutron Agent RPC: get_pvc_port_uuid:"))
        LOG.info(_("- local_port_id: %s"), port_id)
        pvc_port_id = utils.translate_port_id(self.db, port_id, POWERVC_OS)
        LOG.info(_("- pvc_port_id: %s"), pvc_port_id)
        return pvc_port_id

    def get_network(self, context, sync_key):
        LOG.info(_("Neutron Agent RPC: get_network:"))
        LOG.info(_("- sync_key: %s"), sync_key)
        net = self.db.get_network(sync_key=sync_key)
        LOG.info(_("- net: %s"), net)
        return net

    def get_networks(self, context):
        LOG.info(_("Neutron Agent RPC: get_networks:"))
        nets = self.db.get_networks()
        LOG.info(_("- nets: %s"), nets)
        return nets

    def get_subnet(self, context, sync_key):
        LOG.info(_("Neutron Agent RPC: get_subnet:"))
        LOG.info(_("- sync_key: %s"), sync_key)
        subnet = self.db.get_subnet(sync_key=sync_key)
        LOG.info(_("- subnet: %s"), subnet)
        return subnet

    def get_subnets(self, context):
        LOG.info(_("Neutron Agent RPC: get_subnets:"))
        subnets = self.db.get_subnets()
        LOG.info(_("- subnets: %s"), subnets)
        return subnets

    def get_port(self, context, sync_key):
        LOG.info(_("Neutron Agent RPC: get_port:"))
        LOG.info(_("- sync_key: %s"), sync_key)
        port = self.db.get_port(sync_key=sync_key)
        LOG.info(_("- port: %s"), port)
        return port

    def get_ports(self, context):
        LOG.info(_("Neutron Agent RPC: get_ports:"))
        ports = self.db.get_ports()
        LOG.info(_("- ports: %s"), ports)
        return ports

    def set_device_id_on_port_by_pvc_instance_uuid(self,
                                                   context,
                                                   device_id,
                                                   pvc_ins_uuid):
        """
            Query the ports by pvc instance uuid, and set its
            local instance id(device_id).
        """
        LOG.info(_("Neutron Agent RPC: "
                   "set_device_id_on_port_by_pvc_instance_uuid:"))
        LOG.info(_("- device_id: %s"), device_id)
        LOG.info(_("- pvc_ins_uuid: %s"), pvc_ins_uuid)
        local_ids = self.agent.\
            set_device_id_on_port_by_pvc_instance_uuid(self.db,
                                                       device_id,
                                                       pvc_ins_uuid)
        LOG.info(_("- local_ids: %s"), local_ids)
        return local_ids

    def set_pvc_id_to_port(self, context, local_port_id, pvc_port_id):
        LOG.info(_("Neutron Agent RPC: start set pvc id to port:"))
        # Sometimes for db session data delay, repeat 3 times to get the
        # latest port info from local neutron db.
        local_port = None
        breakout = False
        fetchTimes = 0
        while not local_port and not breakout:
            local_port = self.db.get_port(local_id=local_port_id)
            # Delay 3 times, each 10 sec to fetch the local port db obj
            if fetchTimes >= 2:
                breakout = True
            fetchTimes += 1
            LOG.info(_("Cannot get port from local temporarily, wait 10sec.."))
            time.sleep(10)

        self.db.set_port_pvc_id(local_port, pvc_port_id)
        LOG.info(_("End of set powervc uuid to port."))
