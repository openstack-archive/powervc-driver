# Copyright 2013 IBM Corp.

import powervc.common.client.service as service
from powervc.common.client.config import CONF as CONF
from powervc.common.client.config import OS_OPTS as OS_OPTS
from powervc.common.client.config import PVC_OPTS as PVC_OPTS
from powervc.common.constants import SERVICE_TYPES as SERVICE_TYPES

"""sample useage

New PowerVC v1 glance client:

    pvc_glance_v1 = factory.POWERVC.get_client(
            str(constants.SERVICE_TYPES.image), 'v1')

New PowerVC glance client for latest known version:

    pvc_lastest_glance = factory.POWERVC.get_client(
            str(constants.SERVICE_TYPES.image))

New PowerVC cinder client of latest version:

    pvc_cinder_versions = factory.POWERVC.get_versions(
            str(constants.SERVICE_TYPES.volume))

List the services types on the local openstack host:

    known_lcl_service_types = factory.LOCAL.get_service_types()

Get a reference to keystone client for PowerVC:

    pvc_keystone = factory.POWERVC.keystone

"""

# global access to local openstack and powervc services
LOCAL = None
POWERVC = None


if LOCAL is None:
    keystone = service.KeystoneService(str(SERVICE_TYPES.identity),
                                       CONF['openstack']['keystone_version'],
                                       OS_OPTS['auth_url'], OS_OPTS,
                                       None).new_client()
    LOCAL = service.ClientServiceCatalog(OS_OPTS, keystone)

if POWERVC is None:
    keystone_opts = PVC_OPTS.copy()
    keystone_opts['stale_duration']\
        = CONF['powervc']['expiration_stale_duration']
    keystone = service.KeystoneService(str(SERVICE_TYPES.identity),
                                       CONF['powervc']['keystone_version'],
                                       PVC_OPTS['auth_url'], keystone_opts,
                                       None).new_client()
    POWERVC = service.ClientServiceCatalog(PVC_OPTS, keystone)
