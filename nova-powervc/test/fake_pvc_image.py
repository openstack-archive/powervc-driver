COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
    The class FakePVCImage is used to produce
    the fake data of the PowerVC image
"""


class FakePVCImage():

    fake_pvc_image = dict()

    items = [
        "status",
        "updated",
        "id",
        "OS-EXT-IMG-SIZE:size",
        "name",
        "created",
        "minDisk",
        "progress",
        "minRam",
        "os_distro",
        "hypervisor_type",
        "architecture",
        "volume_id"
        ]

    def __init__(self):
        self.fake_pvc_image["status"] = "ACTIVE"
        self.fake_pvc_image["updated"] = "2013-05-17T17:47:45Z"
        self.fake_pvc_image["id"] = "18b28659-966d-4913-bdda-2ca3cc68fb59"
        self.fake_pvc_image["OS-EXT-IMG-SIZE:size"] = 4233
        self.fake_pvc_image["name"] = "RHEL63"
        self.fake_pvc_image["created"] = "2013-05-17T17:47:25Z"
        self.fake_pvc_image["minDisk"] = 0
        self.fake_pvc_image["progress"] = 100
        self.fake_pvc_image["minRam"] = 0
        self.fake_pvc_image["os_distro"] = "rhel"
        self.fake_pvc_image["hypervisor_type"] = "powervm"
        self.fake_pvc_image["architecture"] = "ppc64"
        self.fake_pvc_image["volume_id"] = "6005076802808446B0000000000003C8"

    def update(self, **updates):
        """
        The method "update" is used to update the fake PowerVC image data
        """
        self.fake_pvc_image.update(**updates)
