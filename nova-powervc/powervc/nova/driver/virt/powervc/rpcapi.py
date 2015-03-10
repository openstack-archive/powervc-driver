# Copyright 2013 IBM Corp.

from nova import rpc
from oslo.messaging import Target
from oslo_log import log as logging
from powervc.common.constants import PVC_TOPIC

LOG = logging.getLogger(__name__)

MAX_CACHE_ENTRY = 100


class NetworkAPI(object):
    """
    Client side of the PowerVC Neutron agent RPC API.
    """
    BASE_RPC_API_VERSION = '1.0'

    def __init__(self, topic=None):
        self.topic = topic if topic else PVC_TOPIC
        # Caching the map between local network uuid and pvc network uuid
        # catch[local_uuid] = pvc_uuid
        # Insert entry: when get_pvc_network_uuid is called the first time
        # Delete entry:not supported
        # Capacity limit: no limit set
        self.rpcclient = rpc.get_client(Target(topic=self.topic))
        self._cache = dict()

    def get_pvc_network_uuid(self, ctxt, network_uuid):
        LOG.debug("network_uuid_cache has %s entries" % len(self._cache))
        # in case of upper limit, emit a warning
        if (len(self._cache) > MAX_CACHE_ENTRY):
            # In production env, debug is disabled by default
            # there should not be many networks in real env.
            # log this for reference, this is not supposed to occur
            LOG.warning("network_uuid_cache reach limit:%s" % len(self._cache))
        # check if the entry has been cached
        if network_uuid in self._cache:
            pvc_uuid = self._cache[network_uuid]
            LOG.debug("network_uuid_cache found pvc_uuid %s for %s" %
                      (pvc_uuid, network_uuid))
            return pvc_uuid
        kwargs = {}
        kwargs['network_id'] = network_uuid
        pvc_id = self.rpcclient.call(ctxt, 'get_pvc_network_uuid', **kwargs)
        # in case None, we do not cache it
        if pvc_id:
            # add this entry to cache
            LOG.debug("network_uuid_cache adding pvc_uuid %s for %s to cache" %
                      (pvc_id, network_uuid))
            self._cache[network_uuid] = pvc_id
        return pvc_id

    def get_pvc_port_uuid(self, ctxt, port_uuid):
        LOG.debug("local port-id is %s" % port_uuid)
        kwargs = {}
        kwargs['port_id'] = port_uuid
        pvc_id = self.rpcclient.call(ctxt, 'get_pvc_port_uuid', **kwargs)
        LOG.debug("PowerVC port-id is %s" % pvc_id)
        return pvc_id

    def set_device_id_on_port_by_pvc_instance_uuid(self,
                                                   ctxt,
                                                   local_ins_id,
                                                   pvc_ins_id):
        kwargs = {}
        kwargs['device_id'] = local_ins_id
        kwargs['pvc_ins_uuid'] = pvc_ins_id
        method_name = "set_device_id_on_port_by_pvc_instance_uuid"
        result = self.rpcclient.call(ctxt, method_name, **kwargs)
        return result

    def set_pvc_id_to_port(self, ctxt, local_port_id, pvc_port_id):
        """Set the pvc_port_id to local db port by local_port_id
        """
        kwargs = {}
        kwargs['local_port_id'] = local_port_id
        kwargs['pvc_port_id'] = pvc_port_id
        method_name = "set_pvc_id_to_port"
        result = self.rpcclient.call(ctxt, method_name, **kwargs)
        return result
