# Copyright 2013 IBM Corp.

"""
    The class FakeOSImage is used to produce
    the fake data of the OpenStack image
"""


class FakeOSImage():

    os_image = dict()

    items = [
        'id',
        'name',
        'created_at',
        'updated_at',
        'deleted_at',
        'status',
        'is_public',
        'container_format',
        'disk_format',
        'size'
        ]

    def __init__(self):
        self.os_image['id'] = "18b28659-966d-4913-bdda-2ca3cc68fb59"
        self.os_image['name'] = "RHEL63"
        self.os_image['created_at'] = "2013-05-17T17:47:25Z"
        self.os_image['updated_at'] = "2013-05-17T17:47:45Z"
        self.os_image['status'] = "ACTIVE"
        self.os_image['deleted_at'] = None
        self.os_image['is_public'] = True
        self.os_image['container_format'] = None
        self.os_image['disk_format'] = None
        self.os_image['size'] = 4233

    def update(self, **update):

        self.os_image.update(**update)
