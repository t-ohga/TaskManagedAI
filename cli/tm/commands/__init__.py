from __future__ import annotations

import argparse

from tm.commands import (
    approval,
    auth,
    context,
    doctor,
    memory,
    pr,
    provider,
    repo,
    run,
    secret,
    settings,
    ticket,
)


def register_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    auth.register(subparsers)
    context.register(subparsers)
    doctor.register(subparsers)
    ticket.register(subparsers)
    approval.register(subparsers)
    repo.register(subparsers)
    pr.register(subparsers)
    run.register(subparsers)
    secret.register(subparsers)
    settings.register(subparsers)
    provider.register(subparsers)
    memory.register(subparsers)
