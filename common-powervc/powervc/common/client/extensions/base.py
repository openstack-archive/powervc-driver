# Copyright 2013 IBM Corp.


class ClientExtension(object):
    """base class for all extensions.
    """
    def __init__(self, client):
        self.client = client
