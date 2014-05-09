# Copyright 2013 IBM Corp.


def patch_client(service_wrapper, client):
    org = client.client._cs_request

    """patch the _cs_request method of cinder client and inject
    a keystone managed token and management url. this allows us
    to ensure a valid token is maintained an also support keystone
    v3 apis.
    """
    def _authd_cs_request(url, method, **kwargs):
        # patch cinders HTTPClient to use our keystone for tokens
        # and support for non standard URLs
        client.client.auth_token = service_wrapper.keystone.auth_token
        client.client.management_url = service_wrapper.management_url
        return org(url, method, **kwargs)

    client.client._cs_request = _authd_cs_request
