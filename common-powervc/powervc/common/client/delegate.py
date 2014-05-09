# Copyright 2013 IBM Corp.


def new_composite_deletgate(delegates):
    """create and return a new class which delegates
    calls to the delegates. the facade object returned
    from this method allows you to extend functionality
    of existing objects using containment rather than
    inherritance.

    for example suppose you have obj1 which has method
    x() and you have obj2 which has method y(). you can
    create a single view of those objects like this:

        composite = new_composite_delegate([obj1, obj2])
        composite.x() # calls x() on obj1
        composite.y() # calls y() on obj2

    :param delegates: a list of objects which make up the
    delegates. when a method call or attr access is made
    on the returned wrapper, the list of delegates will
    be tried in order until an object is found with the
    attr.
    """

    class CompositeDelegator(object):
        def __init__(self, *args):
            super(CompositeDelegator, self).__init__()

        def __getattribute__(self, name):
            for instance in delegates:
                if hasattr(instance, name):
                    attr = instance.__getattribute__(name)
                    if hasattr(attr, '__call__'):
                        def _f(*args, **kwargs):
                            return attr(*args, **kwargs)
                        return _f
                    else:
                        return attr
            return None

    return CompositeDelegator()


def context_dynamic_auth_token(ctx, keystone):
    """
    create a delegate specifically for security context
    This is because security context need to access renew
    auth_token for each request. But this property in context
    is static. Delegate this auth_token property to keystone
    dynamic property auth_token.

    Every context created for long live usage should wrap
    this delegate to ensure it always uses the newest
    auth_token for every REST request
    """

    class ContextDAT(ctx.__class__):
        def __init__(self):
            super(ctx.__class__, self).__init__()

        def __getattribute__(self, name):
            if name != 'auth_token':
                if hasattr(ctx, name):
                    attr = ctx.__getattribute__(name)
                    if hasattr(attr, '__call__'):
                        def _f(*args, **kwargs):
                            return attr(*args, **kwargs)
                        return _f
                    else:
                        return attr
            else:
                return keystone.auth_token

    return ContextDAT()
