from interfaces.messenger import ABCMessenger
from smtplib import SMTP
import settings
from my_logging import logger
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

class SmtpAlert(ABCMessenger):

    def __init__(self, loop):
        ABCMessenger.__init__(self, loop)
        logger.info('Connect with {}:{}'.format(settings.smtp_host, settings.smtp_port))
        self.smtp = SMTP(host=settings.smtp_host, port=settings.smtp_port, timeout=5)
        self.smtp.starttls()
        self.smtp.login(settings.smtp_login, settings.smtp_password)
        self.smtp.debuglevel = 0


    def send(self, message, recipients, title):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = title
        msg["From"] = ", ".join(recipients)
        part1 = MIMEText(message)
        msg.attach(part1)
        self.smtp.sendmail(settings.smtp_login, recipients, msg.as_string().encode('ascii'))
