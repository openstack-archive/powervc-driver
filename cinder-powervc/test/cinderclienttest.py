COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
Simple cinder client tests

TODO: Convert to pyunit and use config file
"""

import powervc.common.constants as constants

from powervc.common import config
config.parse_power_config((), 'powervc')
import powervc.common.client.factory as clients


cinder_client = clients.POWERVC.new_client(str(constants.SERVICE_TYPES.volume))

print '=' * 10, 'Listing volumes', '=' * 10
vol_list = cinder_client.volumes.list()
for vol in vol_list:
    print str(vol.display_name), str(vol.display_description), \
        vol.id
