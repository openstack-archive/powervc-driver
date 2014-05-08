COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
    The class FakeVolumeType is used to produce the fake
    data of the OpenStack cinder volume type
"""

import datetime


class FakeVolumeType():

    volume_type = dict()

    items = {
        'created_at',
        'updated_at',
        'deleted_at',
        'deleted',
        'id',
        'name',
        'extra_specs'
    }

    def __init__(self):

        self.volume_type['id'] = "18b28659-966d-4913-bdda-2ca3cc68fb59"
        self.volume_type['created_at'] = \
            datetime.datetime(2013, 8, 12, 5, 59, 25)
        self.volume_type['updated_at'] = \
            datetime.datetime(2013, 8, 12, 5, 59, 25)
        self.volume_type['deleted_at'] = None
        self.os_instance['deleted'] = False
        self.os_instance['name'] = "mengxd-01"
        self.os_instance['extra_specs'] = {
            'drivers:rsize': '2',
            'drivers:storage_pool': 'r3-c3-ch1-jhusta',
            'capabilities:volume_backend_name': 'shared_v7000_1'
        }

    def update(self, **update):

        self.self.volume_type.update(**update)
