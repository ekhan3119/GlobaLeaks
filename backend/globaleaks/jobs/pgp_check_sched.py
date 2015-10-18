
#
#   pgp_check_sched
#   ***************
#
# Implements periodic checks in order to verify pgp key status and other consistencies:
# 
# to be implemented:
#     if keys configured by receiver are going
#     to expire in short time, if so, send a warning email to the recipient.
#
from datetime import timedelta

from cyclone.util import ObjectDict as OD
from twisted.internet.defer import inlineCallbacks

from globaleaks import models
from globaleaks.handlers.admin.node import admin_serialize_node
from globaleaks.handlers.admin.receiver import admin_serialize_receiver
from globaleaks.handlers.admin.notification import get_notification
from globaleaks.handlers.admin.user import get_admin_users
from globaleaks.jobs.base import GLJob
from globaleaks.settings import GLSettings, transact
from globaleaks.utils.mailutils import MIME_mail_build, sendmail
from globaleaks.utils.utility import datetime_now, datetime_null
from globaleaks.utils.templating import Templating


__all__ = ['PGPCheckSchedule']


class PGPCheckSchedule(GLJob):
    name = "PGP Check"

    @transact
    def pgp_validation_check(self, store):
        expired_or_expiring = []

        rcvrs = store.find(models.Receiver)

        for rcvr in rcvrs:
            if rcvr.user.pgp_key_public and rcvr.user.pgp_key_expiration != datetime_null():
                if rcvr.user.pgp_key_expiration < datetime_now():
                    expired_or_expiring.append(admin_serialize_receiver(rcvr, GLSettings.memory_copy.default_language))
                    if GLSettings.memory_copy.allow_unencrypted:
                        # The PGP key status should be downgraded only if the node
                        # accept non PGP mails/files to be sent/stored.
                        # If the node wont accept this the pgp key status
                        # will remain enabled and mail won't be sent by regular flow.
                        rcvr.user.pgp_key_status = u'disabled'
                elif rcvr.user.pgp_key_expiration < datetime_now() - timedelta(days=15):
                    expired_or_expiring.append(admin_serialize_receiver(rcvr, GLSettings.memory_copy.default_language))

        return expired_or_expiring

    @inlineCallbacks
    def send_admin_pgp_alerts(self, admin_desc, expired_or_expiring):
        user_language = admin_desc['language']
        node_desc = yield admin_serialize_node(user_language)
        notification_settings = yield get_notification(user_language)

        fakeevent = OD()
        fakeevent.type = u'admin_pgp_expiration_alert'
        fakeevent.node_info = node_desc
        fakeevent.context_info = None
        fakeevent.receiver_info = None
        fakeevent.tip_info = None
        fakeevent.subevent_info = {'expired_or_expiring': expired_or_expiring}

        body = Templating().format_template(
            notification_settings['admin_pgp_alert_mail_template'], fakeevent)
        title = Templating().format_template(
            notification_settings['admin_pgp_alert_mail_title'], fakeevent)

        admin_users = yield get_admin_users()
        for u in admin_users:
            message = MIME_mail_build(GLSettings.memory_copy.notif_source_name,
                                      GLSettings.memory_copy.notif_source_email,
                                      u['mail_address'],
                                      u['mail_address'],
                                      title,
                                      body)

            yield sendmail(authentication_username=GLSettings.memory_copy.notif_username,
                           authentication_password=GLSettings.memory_copy.notif_password,
                           from_address=GLSettings.memory_copy.notif_source_email,
                           to_address=u['mail_address'],
                           message_file=message,
                           smtp_host=GLSettings.memory_copy.notif_server,
                           smtp_port=GLSettings.memory_copy.notif_port,
                           security=GLSettings.memory_copy.notif_security,
                           event=None)

    @inlineCallbacks
    def send_pgp_alerts(self, receiver_desc):
        user_language = receiver_desc['language']
        node_desc = yield admin_serialize_node(user_language)
        notification_settings = yield get_notification(user_language)

        fakeevent = OD()
        fakeevent.type = u'pgp_expiration_alert'
        fakeevent.node_info = node_desc
        fakeevent.context_info = None
        fakeevent.receiver_info = receiver_desc
        fakeevent.tip_info = None
        fakeevent.subevent_info = None

        body = Templating().format_template(
            notification_settings['pgp_alert_mail_template'], fakeevent)
        title = Templating().format_template(
            notification_settings['pgp_alert_mail_title'], fakeevent)

        to_address = receiver_desc['mail_address']
        message = MIME_mail_build(GLSettings.memory_copy.notif_source_name,
                                  GLSettings.memory_copy.notif_source_email,
                                  to_address,
                                  to_address,
                                  title,
                                  body)

        yield sendmail(authentication_username=GLSettings.memory_copy.notif_username,
                       authentication_password=GLSettings.memory_copy.notif_password,
                       from_address=GLSettings.memory_copy.notif_source_email,
                       to_address=to_address,
                       message_file=message,
                       smtp_host=GLSettings.memory_copy.notif_server,
                       smtp_port=GLSettings.memory_copy.notif_port,
                       security=GLSettings.memory_copy.notif_security,
                       event=None)

    @inlineCallbacks
    def operation(self):
        expired_or_expiring = yield self.pgp_validation_check()

        if expired_or_expiring:
            if not GLSettings.memory_copy.disable_admin_notification_emails:
                admins_descs = yield get_admin_users()
                for admin_desc in admins_descs:
                    yield self.send_admin_pgp_alerts(admin_desc, expired_or_expiring)

            if not GLSettings.memory_copy.disable_receiver_notification_emails:
                for receiver_desc in expired_or_expiring:
                    yield self.send_pgp_alerts(receiver_desc)
