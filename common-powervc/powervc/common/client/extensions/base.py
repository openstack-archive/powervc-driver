COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""


class ClientExtension(object):
    """base class for all extensions.
    """
    def __init__(self, client):
        self.client = client
