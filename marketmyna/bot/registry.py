"""Builds a CommandDispatcher with every command registered - the one
place that ordering (HelpCommand last, see commands/help.py) is handled,
so callers (marketmyna/api/app.py's lifespan, tests, a future CLI) don't each have
to get it right themselves."""

from __future__ import annotations

from typing import Callable, Optional

from .commands.analyze import AnalyzeCommand
from .commands.ask import AskCommand
from .commands.batch import BatchCommand
from .commands.help import HelpCommand
from .commands.markets import CalendarCommand, MarketCommand, ScreenCommand, SectorsCommand
from .commands.portfolio import PortfolioCommand, ReviewCommand, WatchlistCommand
from .commands.research import (
    CompareCommand,
    DividendsCommand,
    EstimatesCommand,
    FinancialsCommand,
    OverviewCommand,
    PeersCommand,
    QuoteCommand,
    ShariahCommand,
    ValuationCommand,
)
from .commands.status import StatusCommand
from .commands.trade import AlertCommand, AlertsCommand, RiskCommand, ScanCommand
from .dispatcher import CommandDispatcher


def build_default_dispatcher(config, scheduler_running: Optional[Callable[[], bool]] = None) -> CommandDispatcher:
    dispatcher = CommandDispatcher()
    for research in (QuoteCommand, OverviewCommand, ValuationCommand, FinancialsCommand, EstimatesCommand,
                     DividendsCommand, PeersCommand, ShariahCommand, CompareCommand):
        dispatcher.register(research(config))
    for market in (MarketCommand, SectorsCommand, ScreenCommand, CalendarCommand):
        dispatcher.register(market(config))
    for own in (PortfolioCommand, ReviewCommand, WatchlistCommand):
        dispatcher.register(own(config))
    dispatcher.register(AnalyzeCommand(config))
    dispatcher.register(BatchCommand(config))
    dispatcher.register(AskCommand(config))
    dispatcher.register(StatusCommand(config, scheduler_running=scheduler_running))
    dispatcher.register(AlertCommand(config))
    dispatcher.register(AlertsCommand(config))
    dispatcher.register(RiskCommand(config))
    dispatcher.register(ScanCommand(config))
    dispatcher.register(HelpCommand(dispatcher))
    return dispatcher
