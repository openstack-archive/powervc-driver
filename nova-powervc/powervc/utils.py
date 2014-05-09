# Copyright 2013 IBM Corp.

"""PowerVC Driver related Utilities"""

from powervc.nova.driver.compute import constants
from powervc.common.gettextutils import _

import logging

LOG = logging.getLogger(__name__)


def normalize_host(hostname):
    """The RPC 'topic.host' format only supports a single '.'"""
    if not hostname:
        return hostname
    return hostname.replace('.', '_')


def get_pvc_id_from_metadata(metadata):
    """
    This method helps to get pvc_id from a list or dict type
    metadata. This util method handles the following situation
    of metadata:
    Type of list sample 1:
        metadata = [
            {'key': 'powervm:defer_placement', 'value': 'true'},
            {'key': 'pvc_id', 'value': '40e2d7c9-b510-4e10-8986-057800117714'}
        ]
    Type of list sample 2:
        metadata = [{
            "powervm:health_status.health_value": "OK",
            "pvc_id": "40e2d7c9-b510-4e10-8986-057800117714"
        }]
    Type of dict sample:
        metadata = {
            "powervm:health_status.health_value": "OK",
            "pvc_id": "40e2d7c9-b510-4e10-8986-057800117714",
            "powervm:defer_placement": "Fale",
            "powervm:max_cpus": "1"
        }
    If none of above types match and pvc_id found, return None
    """
    if not metadata:
        return None

    pvc_id = None

    if (isinstance(metadata, list)):
        # Try to get pvc_id from list type 1
        for meta_list in metadata:
            if meta_list.get('key') == constants.PVC_ID:
                pvc_id = meta_list.get('value')
                LOG.info(_('Found the pvc_id from the list type 1 metadata:%s')
                         % pvc_id)
                return pvc_id
        # If pvc_id not found in list type 1, try list type 2
        for meta_dict in metadata:
            if constants.PVC_ID in meta_dict.keys():
                pvc_id = meta_dict.get(constants.PVC_ID)
                LOG.info(_('Found the pvc_id from the list type 2 metadata:%s')
                         % pvc_id)
                return pvc_id

        # If still not found pvc_id in list, return None
        LOG.info(_('Not found the pvc_id from the list type metadata.'))
        return None

    if (isinstance(metadata, dict)):
        # Try to get pvc_id from dict type
        if constants.PVC_ID in metadata.keys():
            pvc_id = metadata.get(constants.PVC_ID)
            LOG.info(_('Find the pvc_id from the dict type metadata: %s')
                     % pvc_id)
            return pvc_id
        else:
            LOG.info(_('Not found the pvc_id from the dict type metadata.'))
            return None


def fill_metadata_dict_by_pvc_instance(metadata, pvc_instance):
    """
    This common method help to get PowerVC unique property into metadata
    """
    if pvc_instance is None or not isinstance(pvc_instance, dict):
        return {}
    if metadata is None:
        metadata = {}
    LOG.debug(_('metadata before filled: %s') % metadata)

    health_value = None
    health_status = pvc_instance.get('health_status')
    if health_status is not None:
        health_value = health_status.get('health_value')

    metadata[constants.PVC_ID] = pvc_instance['id']

    # The value 'None' of the dict type instance metadata is reserved
    # by the Nova framework.
    # Can not set the value of the instance metadata when it's 'None'.
    if health_value is not None:
        metadata[constants.gen_pvc_key('health_status.health_value')] \
            = health_value

    pvc_attrs = ['cpus', 'min_cpus', 'max_cpus', 'cpu_utilization',
                 'min_vcpus', 'max_vcpus',
                 'min_memory_mb', 'max_memory_mb', 'root_gb']
    for attr in pvc_attrs:
        val = pvc_instance.get(attr)
        if val is not None:
            metadata[constants.gen_pvc_key(attr)] = val

    LOG.debug(_('metadata after filled: %s') % metadata)
    return metadata
