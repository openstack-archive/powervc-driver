COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
    One example of PowerVC network instance:

    "network":{
    "status":"ACTIVE",
    "subnets":[
    ],
    "name":"network-temp",
    "provider:physical_network":"default",
    "admin_state_up":true,
    "tenant_id":"cd8833b1f49c4f1f9c47e8ba1050f916",
    "provider:network_type":"vlan",
    "shared":false,
    "id":"a5f8cf45-1d4d-47b4-b114-b886b3c816da",
    "provider:segmentation_id":1
    }
"""

"""
    The class FakePowerVCNetwork is used to represent the PowerVC Network.
"""


class FakePowerVCNetwork():

    powerNetInstance = dict()

    def __init__(self):

        self.powerNetInstance['status'] = "ACTIVE"
        self.powerNetInstance['subnets'] = None
        self.powerNetInstance['name'] = "network-temp"
        self.powerNetInstance['provider:physical_network'] = "default"
        self.powerNetInstance['admin_state_up'] = True
        self.powerNetInstance['tenant_id'] = "cd8833b1f49c4f1f9c47e8ba1050f916"
        self.powerNetInstance['provider:network_type'] = "vlan"
        self.powerNetInstance['shared'] = False
        self.powerNetInstance['id'] = "a5f8cf45-1d4d-47b4-b114-b886b3c816da"
        self.powerNetInstance['provider:segmentation_id'] = 1

    def update(self, **update):

        self.powerNetInstance.update(**update)
