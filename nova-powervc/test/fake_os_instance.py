COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
    The class FakeOSInstance is used to produce the fake
    data of the OpenStack instance
"""

import datetime


class FakeOSInstance():

    os_instance = dict()

    items = [
        'image_ref',
        'launch_time',
        'launched_at',
        'scheduled_at',
        'memory_mb',
        'vcpus',
        'root_gb',
        'ephemeral_gb',
        'display_name',
        'display_description',
        'locked',
        'instance_type_id',
        'progress',
        'metadata',
        'architecture',
        'host',
        'launched_on',
        'hostname',
        'access_ip_v4',
        'root_device_name',
        'system_metadata',
        'vm_state',
        'task_state',
        'power_state'
        ]

    def __init__(self):

        self.os_instance['image_ref'] = "18b28659-966d-4913-bdda-2ca3cc68fb59"
        self.os_instance['launch_time'] = \
            datetime.datetime(2013, 8, 12, 5, 59, 25)
        self.os_instance['launched_at'] = \
            datetime.datetime(2013, 8, 12, 5, 59, 25)
        self.os_instance['scheduled_at'] = \
            datetime.datetime(2013, 8, 12, 6, 57, 23)
        self.os_instance['memory_mb'] = 2048
        self.os_instance['vcpus'] = 1
        self.os_instance['root_gb'] = 0
        self.os_instance['ephemeral_gb'] = 0
        self.os_instance['display_name'] = "IVT-Test17"
        self.os_instance['display_description'] = "IVT-Test17"
        self.os_instance['locked'] = False
        self.os_instance['instance_type_id'] = 2
        self.os_instance['progress'] = 0
        self.os_instance['metadata'] = {
            'powervm:min_vcpus': '0.10',
            'pvc_id':
            '786d7a82-c6fe-4ee3-bb0b-9faf81f835f9',
            'powervm:cpu_utilization': 0.01,
            'powervm:min_memory_mb': 512,
            'powervm:max_cpus': '',
            'powervm:max_vcpus': '16.00',
            'powervm:min_cpus': '',
            'powervm:max_memory_mb': 8192,
            'powervm:cpus': ''
            }
        self.os_instance['architecture'] = "ppc64"
        self.os_instance['host'] = \
            "blade7_9-5-46-230"
        self.os_instance['launched_on'] = \
            "72bb2b5af241413172ad4cf38354e727ce317843ee2432c36439643c"
        self.os_instance['hostname'] = "IVT-Test17"
        self.os_instance['access_ip_v4'] = None
        self.os_instance['root_device_name'] = None
        self.os_instance['system_metadata'] = "system_metadata"
        self.os_instance['vm_state'] = "active"
        self.os_instance['task_state'] = None
        self.os_instance['power_state'] = 1
        self.os_instance['project_id'] = ""
        self.os_instance['node'] = "IVT-Test17"
        self.os_instance['user_id'] = ''

    def update(self, **update):

        self.self.os_instance.update(**update)

    def get(self, name, default_value=None):
        return self.os_instance.get(name, None)

    def __getitem__(self, name):
        return self.os_instance.get(name)
