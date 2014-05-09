# Copyright 2013 IBM Corp.

"""
    The class FakeOSNetwork is used to represent the OpenStack Network instance
"""


class FakeOSNetwork():

    fakeOSNetworkInstance = dict()

    def __init__(self):

        self.fakeOSNetworkInstance[
            'tenant_id'] = "54c0ae7d58484d8e90bd482015db6b61"
        self.fakeOSNetworkInstance[
            'id'] = "272c42ac-fb16-46df-83b0-64dc5aa6032f"
        self.fakeOSNetworkInstance['name'] = "private"
        self.fakeOSNetworkInstance['status'] = "ACTIVE"
        self.fakeOSNetworkInstance['admin_state_up'] = True
        self.fakeOSNetworkInstance['shared'] = False

    def update(self, **update):

        self.fakeOSNetworkInstance.update(**update)
