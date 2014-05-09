# Copyright 2013 IBM Corp.


def patch_client(service_wrapper, client):

    """ wrapper the _cs_request call in an authenticated version
    of it so we can reuse our keystone connection
    """
    org_cs_request = client.client._cs_request

    def _authd_cs_request(url, method, **kwargs):
        client.client.auth_token = service_wrapper.keystone.auth_token
        client.client.management_url = service_wrapper.management_url
        return org_cs_request(url, method, **kwargs)

    client.client._cs_request = _authd_cs_request
