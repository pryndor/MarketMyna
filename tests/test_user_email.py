"""Reports and alerts by email: which From address and login they use."""

from marketmyna.notifiers.dispatcher import NotificationDispatcher


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
    from marketmyna.core.config import Config

    return Config(email_sender="support@marketmyna.com", email_username="owner@gmail.com",
                  email_reports_sender="reports@marketmyna.com", email_password="app-password",
                  email_smtp_server="smtp.gmail.com", email_smtp_port=587, email_smtp_ssl=False)


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
    NotificationDispatcher(config).send_each({"email": ("Daily report", "body")}, purpose="report")
    assert ("login", "support@marketmyna.com") in _FakeSMTP.log
    assert "support@marketmyna.com" in [e for e in _FakeSMTP.log if e[0] == "from"][0][1]
