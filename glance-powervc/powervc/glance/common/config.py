COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
PowerVC Driver ImageManager Configuration
"""

from oslo.config import cfg
import powervc.common.config as common_config
from powervc.glance.common import constants

CONF = common_config.CONF

# PowerVC Driver ImageManager specific configuration
image_opts = [

    # The image periodic sync interval in seconds. Default is 300.
    cfg.IntOpt('image_periodic_sync_interval_in_seconds',
               default=constants.IMAGE_PERIODIC_SYNC_INTERVAL_IN_SECONDS),

    # In case of error, the image sync retry interval time in seconds. Default
    # is 60.
    cfg.IntOpt('image_sync_retry_interval_time_in_seconds',
               default=constants.IMAGE_SYNC_RETRY_INTERVAL_TIME_IN_SECONDS),

    # The maximum number of images to read for each query request. Default is
    # 500.
    cfg.IntOpt('image_limit', default=constants.IMAGE_LIMIT)
]

CONF.register_opts(image_opts, group='powervc')

# Import glance opts
CONF.import_opt('owner_is_tenant', 'glance.api.middleware.context')


def parse_config(*args, **kwargs):
    common_config.parse_power_config(*args, **kwargs)
