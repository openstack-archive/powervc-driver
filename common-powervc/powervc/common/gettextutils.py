# Copyright 2013 IBM Corp.

import gettext

t = gettext.translation('powervc-driver-common', fallback=True)


def _(msg):
    return t.ugettext(msg)
