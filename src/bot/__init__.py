"""Platform-agnostic chat-bot command layer.

An IncomingMessage (from any platform: Telegram today, a plain HTTP
test endpoint, or a future Discord/Slack listener) goes through
CommandDispatcher, which routes it to a registered Command and returns
a CommandResult - the same text response regardless of where the
message came from.

Only one real inbound listener exists so far: src/bot/telegram_listener.py
(long-polling). The 13 other outbound-only notifier channels in
src/notifiers/ do NOT have an inbound counterpart yet - that's real,
separate follow-up work per platform, not silently implied by this
package's existence.
"""
