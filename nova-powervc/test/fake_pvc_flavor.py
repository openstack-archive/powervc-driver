# Copyright 2013 IBM Corp.

"""
    The class FakePVCFlavor is used to produce
    the fake data of the PowerVC Flavor
"""


class FakePVCFlavor():
    fake_pvc_flavor = dict()

    items = ["name",
             "ram",
             "OS-FLV-DISABLED:disabled",
             "vcpus",
             "swap",
             "os-flavor-access:is_public",
             "rxtx_factor",
             "OS-FLV-EXT-DATA:ephemeral",
             "disk",
             "id"]

    def __init__(self):
        self.fake_pvc_flavor["name"] = "m1.small"
        self.fake_pvc_flavor["ram"] = 2048
        self.fake_pvc_flavor["OS-FLV-DISABLED:disabled"] = False
        self.fake_pvc_flavor["vcpus"] = 1
        self.fake_pvc_flavor["swap"] = ""
        self.fake_pvc_flavor["os-flavor-access:is_public"] = True
        self.fake_pvc_flavor["rxtx_factor"] = 1.0
        self.fake_pvc_flavor["OS-FLV-EXT-DATA:ephemeral"] = 0
        self.fake_pvc_flavor["disk"] = 20
        self.fake_pvc_flavor["id"] = 2

    def update(self, **update):
        self.fake_pvc_flavor.update(**update)
