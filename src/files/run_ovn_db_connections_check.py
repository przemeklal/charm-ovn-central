#!/usr/bin/env python3
"""
This script checks the output of 'ovn-sbctl list connections' for error
conditions.
"""

import sys
import os
import json
from collections import namedtuple
from subprocess import check_output, CalledProcessError

NAGIOS_STATUS_OK = 0
NAGIOS_STATUS_WARNING = 1
NAGIOS_STATUS_CRITICAL = 2
NAGIOS_STATUS_UNKNOWN = 3

NAGIOS_STATUS = {
    NAGIOS_STATUS_OK: "OK",
    NAGIOS_STATUS_WARNING: "WARNING",
    NAGIOS_STATUS_CRITICAL: "CRITICAL",
    NAGIOS_STATUS_UNKNOWN: "UNKNOWN",
}

OUTPUT_FILE = "/var/lib/nagios/ovn_db_connections.out"
OVNSB_DB_CTL = "/var/run/ovn/ovnsb_db.ctl"
TMP_OUTPUT_FILE = OUTPUT_FILE + ".tmp"

EXPECTED_CONNECTIONS = 2

Alert = namedtuple("Alert", "status msg")


def get_uuid(connection):
    return connection["_uuid"][1]


def check_role_target(connection):
    uuid = get_uuid(connection)

    if connection["target"] not in ["pssl:6642", "pssl:16642"]:
        msg = "{}: unexpected target: {}".format(uuid, connection["target"])
        return Alert(NAGIOS_STATUS_CRITICAL, msg)

    if connection["role"] not in ["ovn-controller", ""]:
        msg = "{}: unexpected role: {}".format(uuid, connection["role"])
        return Alert(NAGIOS_STATUS_CRITICAL, msg)

    if connection["target"] == "pssl:6642":
        if connection["role"] == "ovn-controller":
            msg = "{}: role ovn-controller uses target pssl:6642".format(uuid)
            return Alert(NAGIOS_STATUS_OK, msg)
        elif connection["role"] == "":
            msg = "{}: RBAC is disabled".format(uuid)
            return Alert(NAGIOS_STATUS_WARNING, msg)

    elif connection["target"] == "pssl:16642":
        if connection["role"] == "":
            msg = '{}: role "" uses target pssl:16642'.format(uuid)
            return Alert(NAGIOS_STATUS_OK, msg)
        else:
            msg = "{}: target pssl:16642 should not be used by role {}".format(
                uuid, connection["role"]
            )
            return Alert(NAGIOS_STATUS_CRITICAL, msg)


def check_read_only(connection):
    uuid = get_uuid(connection)
    if connection["read_only"] is not False:
        return Alert(
            NAGIOS_STATUS_CRITICAL, "{}: connection is read only".format(uuid)
        )
    return Alert(
        NAGIOS_STATUS_OK, "{}: connection is not read_only".format(uuid)
    )


def check_connections(connections):
    alerts = []
    controllers_count = 0

    if len(connections) != EXPECTED_CONNECTIONS:
        alerts.append(
            Alert(
                NAGIOS_STATUS_CRITICAL,
                "expected 2 ovn-sb connections, got {}".format(
                    len(connections)
                ),
            )
        )

    for conn in connections:
        if conn["role"] == "ovn-controller":
            controllers_count += 1
        alerts.append(check_role_target(conn))
        alerts.append(check_read_only(conn))

    # assert that exactly 1 controller connection exists
    if controllers_count != 1:
        alerts.append(
            Alert(
                NAGIOS_STATUS_CRITICAL,
                "expected 1 ovn-controller connection, got {}".format(
                    controllers_count
                ),
            )
        )

    return alerts


def parse_output(raw):
    status = json.loads(raw)
    data = status["data"]
    headings = status["headings"]
    connections = []
    for d in data:
        connections.append(dict(zip(headings, d)))
    return check_connections(connections)


def write_output_file(output):
    """Write results of checks to the defined location for nagios to check."""
    try:
        with open(TMP_OUTPUT_FILE, "w") as fd:
            fd.write(output)
    except IOError as e:
        print(
            "Cannot write output file {}, error {}".format(TMP_OUTPUT_FILE, e)
        )
        sys.exit(1)
    os.rename(TMP_OUTPUT_FILE, OUTPUT_FILE)


def is_leader():
    cmd = [
        "ovs-appctl",
        "-t",
        OVNSB_DB_CTL,
        "cluster/status",
        "OVN_Southbound",
    ]
    output = check_output(cmd).decode("utf-8")

    output_lines = output.split("\n")
    role_line = [line for line in output_lines if line.startswith("Role:")]

    if len(role_line) > 0:
        _, role = role_line[0].split(":")
        return role.strip() == "leader"
    else:
        print(
            "'Role:' line not found in the output of '{}'".format(
                " ".join(cmd)
            )
        )
        return False


def aggregate_alerts(alerts):
    total_crit = 0
    total_warn = 0

    msg_crit = []
    msg_warn = []
    msg_ok = []

    for a in alerts:
        if a.status == NAGIOS_STATUS_CRITICAL:
            total_crit += 1
            msg_crit.append(a.msg)
        elif a.status == NAGIOS_STATUS_WARNING:
            total_warn += 1
            msg_warn.append(a.msg)
        else:
            msg_ok.append(a.msg)

    severity = "OK"
    status_detail = ""

    if total_crit > 0:
        severity = "CRITICAL"
        status_detail = "; ".join(
            [status_detail, "critical[{}]: {}".format(total_crit, msg_crit)]
        )
    if total_warn > 0:
        if severity != "CRITICAL":
            severity = "WARNING"
        status_detail = "; ".join(
            [status_detail, "warnings[{}]: {}".format(total_warn, msg_warn)]
        )
    if total_crit == 0 and total_crit == 0:
        status_detail = "no issues"

    return "{}: {}".format(severity, status_detail)


def run_checks():
    output = "UNKNOWN"
    try:
        if is_leader():
            cmd = ["ovn-sbctl", "--format=json", "list", "connection"]
            cmd_output = check_output(cmd).decode("utf-8")
            alerts = parse_output(cmd_output)
            output = aggregate_alerts(alerts)
        else:
            output = "no-op (unit is not the DB leader)"
    except CalledProcessError as error:
        output = "UKNOWN: {}".format(error.stdout.decode(errors="ignore"))

    write_output_file(output)


if __name__ == "__main__":
    run_checks()
