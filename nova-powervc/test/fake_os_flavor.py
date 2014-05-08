COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
    The class FakeOSFlavor is used to produce
    the fake data of the OpenStack Flavor
"""


class FakeOSFlavor():

    os_flavor = dict()

    items = [
        'id',
        'name',
        'memory_mb',
        'vcpus',
        'root_gb',
        'ephemeral_gb',
        'flavorid',
        'swap',
        'rxtx_factor',
        'vcpu_weight',
        ]

    def __init__(self):

        self.os_flavor['id'] = 2
        self.os_flavor['name'] = "m1.small"
        self.os_flavor['memory_mb'] = 2048
        self.os_flavor['vcpus'] = 1
        #FixMe Don't know what are proper values for the property "root_gb",
        #"ephemeral_gb", "flavorid"
        self.os_flavor['root_gb'] = 0
        self.os_flavor['ephemeral_gb'] = 0
        self.os_flavor['flavorid'] = "fakeflavorid"
        self.os_flavor['swap'] = ""
        self.os_flavor['rxtx_factor'] = 1.0
        self.os_flavor['vcpu_weight'] = None

    def update(self, **update):

        self.os_flavor.update(**update)
