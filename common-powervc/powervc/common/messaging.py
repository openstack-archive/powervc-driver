# Copyright 2014 IBM Corp.

"""This module contains common structures and functions that help to handle
AMQP messages based on olso.messaging framework.
"""

import fnmatch
import logging
import inspect
import socket
import threading
import time

from oslo.messaging import target
from oslo.messaging import transport
from oslo.messaging.notify import dispatcher
from oslo.messaging.notify import listener

LOG = logging.getLogger(__name__)


class NotificationEndpoint(object):
    """Message listener endpoint, used to register handler functions, receive
    and dispatch notification messages.
    """
    MSG_LEVEL = {0: 'AUDIT', 1: 'DEBUG', 2: 'INFO', 3: 'WARN',
                 4: 'ERROR', 5: 'CRITICAL', 6: 'SAMPLE'}

    def __init__(self, log=None, sec_context=None):
        """Create a NotificationEndpoint object, the core part of a listener.

        :param: log logger used when handle messages.
        :param: sec_context this is a security context contains keystone auth.
                token for API access, not the context sent by message notifier.
        """
        self._handler_map = {}
        self._log = log
        self._sec_ctxt = sec_context

    def audit(self, ctxt, publisher_id, event_type, payload, metadata):
        """Receive a notification at audit level."""
        return self._dispatch(0, ctxt, publisher_id,
                              event_type, payload, metadata)

    def debug(self, ctxt, publisher_id, event_type, payload, metadata):
        """Receive a notification at debug level."""
        return self._dispatch(1, ctxt, publisher_id,
                              event_type, payload, metadata)

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        """Receive a notification at info level."""
        return self._dispatch(2, ctxt, publisher_id,
                              event_type, payload, metadata)

    def warn(self, ctxt, publisher_id, event_type, payload, metadata):
        """Receive a notification at warning level."""
        return self._dispatch(3, ctxt, publisher_id,
                              event_type, payload, metadata)

    def error(self, ctxt, publisher_id, event_type, payload, metadata):
        """Receive a notification at error level."""
        return self._dispatch(4, ctxt, publisher_id,
                              event_type, payload, metadata)

    def critical(self, ctxt, publisher_id, event_type, payload, metadata):
        """Receive a notification at critical level."""
        return self._dispatch(5, ctxt, publisher_id,
                              event_type, payload, metadata)

    def sample(self, ctxt, publisher_id, event_type, payload, metadata):
        """Receive a notification at sample level.

        Sample notifications are for high-frequency events
        that typically contain small payloads. eg: "CPU = 70%"

        Not all drivers support the sample level
        (log, for example) so these could be dropped.
        """
        return self._dispatch(6, ctxt, publisher_id,
                              event_type, payload, metadata)

    def _dispatch(self, level, ctxt, publisher_id, event_type, payload,
                  metadata):
        """Route message to handlers according event_type registered.
        """

        handlers = self._get_handlers(event_type)
        try:
            if handlers:
                if self._log:
                    self._log.info("'%s' level '%s' type message is received. "
                                   "Routing to handlers..."
                                   % (self.MSG_LEVEL[level], event_type)
                                   )
                for handler in handlers:
                    start_time = time.time()
                    handler(context=self._sec_ctxt,
                            ctxt=ctxt,
                            event_type=event_type,
                            payload=payload,
                            )
                    end_time = time.time()
                    if self._log:
                        self._log.debug("handler '%s' uses '%f' time(s)"
                                        % (handler, end_time - start_time)
                                        )
            return dispatcher.NotificationResult.HANDLED
        except Exception:
            self._log.exception("Error handling '%(level)s' level '%(type)s' "
                                "type message '%(msg)s'."
                                % {'level': self.MSG_LEVEL[level],
                                   'type': event_type,
                                   'msg': payload,
                                   }
                                )
            # TODO(gpanda): consider if requeue is needed in the future,
            # not all transport drivers implement support for requeueing, if
            # the driver does not support requeueing, it will raise
            # NotImplementedError. As far as I tested(oslo.messaging 1.3.1 +
            # qpidd 0.14), it doesn't support.
            # return dispatcher.NotificationResult.REQUEUE
        finally:
            pass

    def _get_handlers(self, event_type):
        """Get a list of all the registered handlers that match the given event
        type.
        """
        handlers = []
        for event_type_pattern in self._handler_map:
            if fnmatch.fnmatch(event_type, event_type_pattern):
                handlers.append(self._handler_map.get(event_type_pattern))
        return handlers

    def register_handler(self, event_type, handler):
        """Register a handler function for one or more message notification
        event types. The handler function will be called when a message is
        received that matches the event type. The handler function will be
        passed two arguments: the security context and a dictionary containing
        the message attributes. The message attributes include: event_type,
        timestamp, message_id, priority, publisher_id, payload.

        The following wildcards are allowed when registering an event type
        handler (see the documentation for fnmatch):

          *        matches everything
          ?        matches any single character
          [seq]    matches any character in seq
          [!seq]   matches any character not in seq

        For example, registering the following event type handler will cause
        the handler function to be called for any event type starting with
        'compute.instance.'.

          listener = conn.register_handler('compute.instance.*',
                                           self.handle_instance_messages)

        If a single notification event type matches multiple registered
        handlers, each matching handler will be called. The order in which the
        handlers are called is not guaranteed. If the execution order is
        important for the multiple handlers of a single event type then ensure
        that only a single handler will be called for the event type and
        perform the multiple operations in the single handler.

        :param: event_type The event type or list of event types to associate
                           with the handler
        :param: handler The handler function to handle a message with the given
                        event type
        """
        if not isinstance(event_type, list):
            event_type = [event_type]
        for et in event_type:
            self._handler_map[et] = handler


def _start_notification_listener(notification_listener):
    def _run():
        notification_listener.start()
        notification_listener.wait()

    """
    A listener blocks while it waits for the next message on the queue,
    so we initiate a thread to run the listening function.
    """
    t = threading.Thread(target=_run)
    t.start()


def _get_pool_name(exchange):
    """Get the pool name for the listener, it will be formated as
    'powervdriver-exchange-hostname'

    :param: exchange exchange name
    """
    pool_name = 'powervcdriver-%s-%s' % (exchange, socket.gethostname())
    LOG.info("Listener pool name is %s" % pool_name)
    return pool_name


def start_listener(conf, exchange, topic, endpoints):
    """Start up  notification listener

    :param: conf configuration object for listener
    :param: exchange exchange name
    :param: topic topic name
    :param: endpoints the listener endpoints
    """
    trans = transport.get_transport(conf)
    targets = [target.Target(exchange=exchange, topic=topic)]
    create_listener = listener.get_notification_listener
    if 'pool' in inspect.getargspec(create_listener).args:
        pool_name = _get_pool_name(exchange)
        mylistener = create_listener(trans, targets, endpoints,
                                     allow_requeue=False, pool=pool_name)
    else:
        mylistener = create_listener(trans, targets, endpoints,
                                     allow_requeue=False)
    _start_notification_listener(mylistener)
