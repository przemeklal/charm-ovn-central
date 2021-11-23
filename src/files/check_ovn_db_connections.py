#!/usr/bin/env python3

import os

from nagios_plugin3 import (
    CriticalError,
    UnknownError,
    WarnError,
    check_file_freshness,
    try_check,
)

OUTPUT_FILE = "/var/lib/nagios/ovn_db_connections.out"

NAGIOS_ERRORS = {
    "CRITICAL": CriticalError,
    "UNKNOWN": UnknownError,
    "WARNING": WarnError,
}


def parse_output():
    if not os.path.exists(OUTPUT_FILE):
        raise UnknownError(
            "UNKNOWN: {} does not exist (yet?)".format(OUTPUT_FILE)
        )

    # Check if file is newer than 10min
    try_check(check_file_freshness, OUTPUT_FILE)

    try:
        with open(OUTPUT_FILE, "r") as fd:
            output = fd.read()
    except PermissionError as error:
        raise UnknownError(error)

    for startline in NAGIOS_ERRORS:
        if output.startswith("{}: ".format(startline)):
            func = NAGIOS_ERRORS[startline]
            raise func(output)

    print("OK: {}".format(output))


if __name__ == "__main__":
    try_check(parse_output)
