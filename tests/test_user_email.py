"""Reports and alerts by email to a user's own confirmed address (accounts mode)."""

from src.notifiers.dispatcher import NotificationDispatcher
from src.services import accounts


class _FakeSMTP:
    """Records the login and the From of each message instead of sending."""

    log: list = []

    def __init__(self, host, port, timeout=None):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        self.log.append(("login", user))

    def send_message(self, msg):
        self.log.append(("from", msg["From"], msg["To"]))

    def quit(self):
        pass


def _gmail_config():
    from src.core.config import Config

    return Config(email_sender="support@marketmyna.com", email_username="owner@gmail.com",
                  email_reports_sender="reports@marketmyna.com", email_password="app-password",
                  email_smtp_server="smtp.gmail.com", email_smtp_port=587, email_smtp_ssl=False)


def test_gmail_send_as_logs_in_as_gmail_and_sends_as_the_alias(monkeypatch):
    import smtplib

    from src.notifiers.email import EmailSender

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.log = []
    config = _gmail_config()
    assert accounts.send_user_email(config, "asha@example.com", "Daily report", "body", purpose="report")
    assert accounts.send_user_email(config, "asha@example.com", "Alert", "body", purpose="alert")
    assert EmailSender(config).send("Confirm your email")
    froms = [entry[1] for entry in _FakeSMTP.log if entry[0] == "from"]
    assert [entry[1] for entry in _FakeSMTP.log if entry[0] == "login"] == ["owner@gmail.com"] * 3
    assert "reports@marketmyna.com" in froms[0] and "reports@marketmyna.com" in froms[1]  # report, alert
    assert "support@marketmyna.com" in froms[2]


def test_owner_email_channel_sends_reports_and_alerts_from_the_reports_address(monkeypatch):
    import smtplib

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.log = []
    dispatcher = NotificationDispatcher(_gmail_config())
    dispatcher.send_each({"email": ("Daily report", "body")}, purpose="report")
    dispatcher.send_all("RELIANCE above 3000", title="Alert: RELIANCE", purpose="alert")
    dispatcher.send_all("disk full", title="error", purpose="system_error")
    froms = [entry[1] for entry in _FakeSMTP.log if entry[0] == "from"]
    assert "reports@marketmyna.com" in froms[0] and "reports@marketmyna.com" in froms[1]
    assert "support@marketmyna.com" in froms[2]


def test_without_a_reports_address_everything_uses_the_sender(monkeypatch):
    import smtplib
    from dataclasses import replace

    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    _FakeSMTP.log = []
    config = replace(_gmail_config(), email_reports_sender=None, email_username=None)
    assert accounts.send_user_email(config, "asha@example.com", "Daily report", "body", purpose="report")
    assert ("login", "support@marketmyna.com") in _FakeSMTP.log
    assert "support@marketmyna.com" in [e for e in _FakeSMTP.log if e[0] == "from"][0][1]
