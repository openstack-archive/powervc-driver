# Copyright 2013 IBM Corp.


def patch_client(service_wrapper, client):
    org_auth_and_fetch = client.httpclient.authenticate_and_fetch_endpoint_url

    """patch the authenticate_and_fetch_endpoint_url method to inject
    our own managed keystone token and endpoint
    """
    def _patched_auth_and_fetch():
        # inject our keystone managed token
        client.httpclient.auth_token = service_wrapper.keystone.auth_token
        client.httpclient.endpoint_url = service_wrapper.management_url
        return org_auth_and_fetch()

    client.httpclient.authenticate_and_fetch_endpoint_url = \
        _patched_auth_and_fetch
