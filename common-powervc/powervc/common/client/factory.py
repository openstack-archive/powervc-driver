# Copyright 2013 IBM Corp.

import time
import logging
import powervc.common.client.service as service
from powervc.common.client.config import CONF as CONF
from powervc.common.client.config import OS_OPTS as OS_OPTS
from powervc.common.client.config import PVC_OPTS as PVC_OPTS
from powervc.common.constants import SERVICE_TYPES as SERVICE_TYPES
from powervc.common.gettextutils import _

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
LOG = logging.getLogger(__name__)


def initialize_local_servicecatalog():
    global LOCAL
    if LOCAL:
        return

    def new_local_servicecatalog():
        LOG.info(_('start to new local keystone client'))
        keystone_version = CONF['openstack']['keystone_version']
        keystone = service.KeystoneService(str(SERVICE_TYPES.identity),
                                           keystone_version,
                                           OS_OPTS['auth_url'], OS_OPTS,
                                           None).new_client()
        servicecatalog = service.ClientServiceCatalog(OS_OPTS, keystone)
        LOG.info(_('finish to new local keystone client'))
        return servicecatalog

    count = 0
    while count < CONF['openstack']['keystone_max_try_times']:
        try:
            if LOCAL:
                return
            LOCAL = new_local_servicecatalog()
            return
        except Exception, e:
            LOG.info(_('Keystone service is not ready. %s ' % unicode(e)))
            count += 1
            if count == CONF['openstack']['keystone_max_try_times']:
                LOG.error(_('Keystone service is not ready eventually after'
                            ' retries!'))
                raise e
            time.sleep(CONF['openstack']['keystone_retry_interval'])

if LOCAL is None:
    initialize_local_servicecatalog()

if POWERVC is None:
    keystone_opts = PVC_OPTS.copy()
    keystone_opts['stale_duration']\
        = CONF['powervc']['expiration_stale_duration']
    keystone = service.KeystoneService(str(SERVICE_TYPES.identity),
                                       CONF['powervc']['keystone_version'],
                                       PVC_OPTS['auth_url'], keystone_opts,
                                       None).new_client()
    POWERVC = service.ClientServiceCatalog(PVC_OPTS, keystone)
