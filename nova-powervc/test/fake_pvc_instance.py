COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013, 2014 All Rights Reserved

*************************************************************
"""

"""
    The class FakePVCInstance is used to produce
    the fake data of the PowerVC instance
"""


class FakePVCInstance():

    pvc_instance = dict()

    items = [
        "status",
        "updated",
        "hostId",
        "cpu_utilization",
        "key_name",
        "max_vcpus",
        "OS-EXT-STS:task_state",
        "OS-EXT-SRV-ATTR:host",
        "OS-EXT-STS:vm_state",
        "OS-EXT-SRV-ATTR:instance_name",
        "vcpu_mode",
        "id",
        "OS-EXT-SRV-ATTR:hypervisor_hostname",
        "min_memory_mb",
        "max_memory_mb",
        "user_id",
        "name",
        "created",
        "tenant_id",
        "min_vcpus",
        "OS-DCF:diskConfig",
        "vcpus",
        "memory_mb",
        "accessIPv4",
        "accessIPv6",
        "progress",
        "OS-EXT-STS:power_state",
        "OS-EXT-AZ:availability_zone",
        "memory_mode",
        "launched_at",
        "scheduled_at",
        "cpus"
        "min_cpus",
        "max_cpus",
        "OS-EXT-SRV-ATTR:hypervisor_hostname",
        "health_status"
    ]

    _info = None

    def __init__(self):
        self.pvc_instance["status"] = "ACTIVE"
        self.status = self.pvc_instance["status"]
        self.pvc_instance["updated"] = "2013-07-08T20:52:26Z"
        self.pvc_instance["hostId"] = \
            "72bb2b5af241413172ad4cf38354e727ce317843ee2432c36439643c"
        self.pvc_instance["cpu_utilization"] = 0.01
        self.pvc_instance["key_name"] = None
        self.pvc_instance["max_vcpus"] = "16.00"
        self.pvc_instance["OS-EXT-STS:task_state"] = None
        self.pvc_instance["OS-EXT-SRV-ATTR:host"] = "blade7_9-5-46-230"
        self.__dict__["OS-EXT-SRV-ATTR:host"] = \
            self.pvc_instance["OS-EXT-SRV-ATTR:host"]
        self.pvc_instance["OS-EXT-STS:vm_state"] = "active"
        self.pvc_instance["OS-EXT-SRV-ATTR:instance_name"] = \
            "nova-ngp02-05-powervc--00000012"
        self.pvc_instance["vcpu_mode"] = "shared"
        self.pvc_instance["id"] = "786d7a82-c6fe-4ee3-bb0b-9faf81f835f9"
        self.id = self.pvc_instance["id"]
        self.pvc_instance["OS-EXT-SRV-ATTR:hypervisor_hostname"] = \
            "ngp02-07.rch.kstart.ibm.com"
        self.pvc_instance["min_memory_mb"] = 512
        self.pvc_instance["max_memory_mb"] = 8192
        self.pvc_instance["user_id"] = "499443d298384e4f8cba0705789a523c"
        self.pvc_instance["name"] = "IVT-Test17"
        self.pvc_instance["created"] = "2013-05-17T21:28:35Z"
        self.pvc_instance["tenant_id"] = "67ebad6b205a4b4a9582684c709f816c"
        self.pvc_instance["min_vcpus"] = "0.10"
        self.pvc_instance["OS-DCF:diskConfig"] = "MANUAL"
        self.pvc_instance["vcpus"] = "0.10"
        self.pvc_instance["memory_mb"] = 2048
        self.pvc_instance["accessIPv4"] = ""
        self.pvc_instance["accessIPv6"] = ""
        self.pvc_instance["progress"] = 0
        self.pvc_instance["OS-EXT-STS:power_state"] = 1
        self.pvc_instance["OS-EXT-AZ:availability_zone"] = "nova"
        self.pvc_instance["memory_mode"] = "dedicated"
        self.pvc_instance["launched_at"] = 1376287165.55
        self.pvc_instance["scheduled_at"] = 1376290643.2
        self.pvc_instance["cpus"] = ""
        self.pvc_instance["min_cpus"] = ""
        self.pvc_instance["max_cpus"] = ""
        self.pvc_instance["OS-EXT-SRV-ATTR:hypervisor_hostname"] = "IVT-Test17"
        self.health_status = {u'health_value': u'WARNING'}

        # Here is just a slice of data in an completed structure of _info
        # attribute of pvc instance, refer to sample_pvc_instance.json for the
        # whole image of an pvc instance and the _info in it.
        self._info = {
            'max_memory_mb': 8192,
            'memory_mb': 2048,
            'cpus': 2,
            'OS-EXT-STS:power_state': 1
        }

    def update(self, **update):
        self.pvc_instance.update(**update)
