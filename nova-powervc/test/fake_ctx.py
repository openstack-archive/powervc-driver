COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

"""
    The class FakeCTX is used to produce the fake data of CTX
"""


class FakeCTX():

    user_id = None
    project_id = None

    def __init__(self):

        self.user_id = "testuser"
        self.project_id = "testproject"

    def update(self, **update):

        if not update:
            self.user_id = update['user_id']
            self.project_id = update['project_id']
