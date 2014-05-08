COPYRIGHT = """
*************************************************************
Licensed Materials - Property of IBM

OCO Source Materials

(C) Copyright IBM Corp. 2013 All Rights Reserved
*************************************************************
"""

import gettext

t = gettext.translation('powervc-driver-common', fallback=True)


def _(msg):
    return t.ugettext(msg)
