#!/usr/bin/env python3
"""
Rename the onboard LAN interface on Debian hosts (ifupdown, /etc/network/interfaces)
via a systemd .link file matched by permanent MAC address.

Usage:
    ./rename_iface.py                                                           # dry-run (nothing is changed)
    ./rename_iface.py --apply                                                   # edit files, no reboot
    ./rename_iface.py --apply --reboot                                          # edit files + reboot + verify result
    ./rename_iface.py --apply --only pc-iface@192.0.2.11 pc-iface@192.0.2.12    # use these hosts, ignore HOSTS
    ./rename_iface.py --apply --reboot --timeout 900                            # wait longer for slow hosts

Run this BEFORE installing the 10GbE card. Keep console access in case a host
does not come back. The reboot is skipped on a host when the old name is still
used outside /etc/network (WARNING) or when no network file uses the new name.
Rollback on a host (every edited file has a dated backup, take the ones from the run day):
    for b in /etc/network/*.bak.<YYYY-MM-DD> /etc/network/*/*.bak.<YYYY-MM-DD>; do sudo cp "$b" "${b%.bak.*}"; done
    sudo rm /etc/systemd/network/10-lan1g.link && sudo update-initramfs -u
"""
import argparse
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

NEW_NAME_IFACE = "lan1g"

HOSTS = [
    "pc-iface@192.0.2.11",
    "pc-iface@192.0.2.12",
    "pc-iface@192.0.2.13",
]

# ServerAlive*: drop a stalled connection (host half-down during reboot) after ~15s instead of hanging
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3"]
LINK_PATH = f"/etc/systemd/network/10-{NEW_NAME_IFACE}.link"
BOOT_TIMEOUT = 600  # seconds to wait for the host to come back after reboot


def ssh(host, cmd, input=None):
    r = subprocess.run(["ssh", *SSH_OPTS, host, cmd], input=input, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"exit code {r.returncode}")
    return r.stdout.strip()


def pick_nic(text):
    """Return (name, MAC) of the single physical NIC that is UP in `ip -br link` output."""
    nics = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        if "@" in parts[0] or "." in parts[0]:  # VLAN / macvlan: enp4s0.100@enp4s0
            continue
        name, state, mac = parts[0], parts[1], parts[2]
        if name.startswith("e") and state == "UP":
            nics.append((name, mac))

    if len(nics) != 1:
        raise RuntimeError(f"expected exactly one NIC, found {len(nics)}: {nics}")
    return nics[0]


def discover(host, link_text):
    """Return (name, permanent MAC) of the single physical NIC that is UP."""
    name, mac = pick_nic(link_text)
    if not re.fullmatch(r"[a-z0-9]+", name):
        raise RuntimeError(f"unexpected interface name {name!r}")
    # PermanentMACAddress only matches real hardware MACs; refuse a spoofed one.
    if ssh(host, f"cat /sys/class/net/{name}/addr_assign_type") != "0":
        raise RuntimeError(f"{name} does not use its permanent MAC ({mac}); set it by hand")
    return name, mac


def already_done(link_text):
    return any(l.split()[0] == NEW_NAME_IFACE for l in link_text.splitlines() if l.strip())


def write_link(host, mac, old):
    content = (
        f"[Match]\nPermanentMACAddress={mac}\nType=ether\n\n"
        f"[Link]\nName={NEW_NAME_IFACE}\n"
    )
    ssh(host, "sudo -n mkdir -p /etc/systemd/network")
    ssh(host, f"sudo -n tee {LINK_PATH} > /dev/null", input=content)
    # Prove udev will apply the file before we touch the network config.
    test = ssh(host, f"sudo -n udevadm test-builtin net_setup_link /sys/class/net/{old} 2>&1")
    if f"10-{NEW_NAME_IFACE}.link" not in test:
        raise RuntimeError(f"udev does not pick up {LINK_PATH}:\n{test}")
    return ssh(host, f"cat {LINK_PATH}")


def edit_network_config(host, old):
    """Backup, replace the old name everywhere in /etc/network.

    Return (ready, leftovers): ready = a network file uses the new name,
    leftovers = lines elsewhere in /etc that still use the old name.
    """
    # dated and -n: a same-day rerun keeps the first (original) copy
    ssh(host, "sudo -n cp -n /etc/network/interfaces /etc/network/interfaces.bak.$(date +%F)")
    files = ssh(host, f"sudo -n grep -rIl --exclude='*.bak*' -w {old} /etc/network || true").split()
    for f in files:
        ssh(host, f"sudo -n cp -n {f} {f}.bak.$(date +%F)")  # every edited file gets a backup, not only interfaces
        ssh(host, f"sudo -n sed -i 's/\\b{old}\\b/{NEW_NAME_IFACE}/g' {f}")
    ready = bool(ssh(host, f"sudo -n grep -rIl --exclude='*.bak*' -w {NEW_NAME_IFACE} /etc/network || true"))
    left = ssh(host, f"sudo -n grep -rIn --exclude='*.bak*' --exclude-dir=initramfs-tools -w {old} /etc || true")
    return ready, left


def wait_for_new_name(host, timeout):
    time.sleep(15)  # let the host actually go down first
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for line in ssh(host, "ip -br addr").splitlines():
                parts = line.split()
                if parts[0] == NEW_NAME_IFACE and parts[1] == "UP" and any("." in p for p in parts[2:]):
                    return line
        except RuntimeError:
            pass
        time.sleep(5)
    raise RuntimeError(f"{host} did not come back with {NEW_NAME_IFACE} within {timeout}s; use the console")


def process(host, apply, reboot, timeout):
    try:
        link_text = ssh(host, "ip -br link")
        if already_done(link_text):
            return host, f"{NEW_NAME_IFACE} already exists, skipped", None
        ssh(host, "sudo -n true")  # fail early: later greps end in `|| true` and would hide a sudo error
        old, mac = discover(host, link_text)
        msg = f"{old} ({mac}) -> {NEW_NAME_IFACE}"
        if not apply:
            hits = ssh(host, f"sudo -n grep -rIn --exclude='*.bak*' -w {old} /etc || true")
            return host, msg + "\n--- would change ---\n" + (hits or "(no references found)"), None

        msg += "\n--- wrote link file ---\n" + write_link(host, mac, old)
        ready, left = edit_network_config(host, old)
        if left:
            msg += f"\n--- WARNING: fix these by hand (still use {old}) ---\n" + left
        if not ready:
            msg += f"\n--- WARNING: no file in /etc/network uses {NEW_NAME_IFACE}; do not reboot yet ---"
        ssh(host, "sudo -n update-initramfs -u")

        if reboot and (left or not ready):
            msg += "\n--- NOT rebooting: " + (
                f"{old} is still used outside /etc/network" if left
                else f"no file in /etc/network uses {NEW_NAME_IFACE}") + "; fix it, then rerun ---"
            return host, msg, "not rebooted"  # error set so the exit code is 1
        elif reboot:
            r = subprocess.run(["ssh", *SSH_OPTS, host, "sudo -n systemctl reboot"], capture_output=True, text=True)
            if r.returncode not in (0, 255):  # 255: connection dropped by the reboot
                raise RuntimeError(f"reboot command failed: {r.stderr.strip() or r.returncode}")
            msg += "\n--- after reboot ---\n" + wait_for_new_name(host, timeout)
        else:
            msg += "\n(no reboot: the new name is active after the next reboot)"
        return host, msg, None
    except Exception as e:
        return host, None, str(e)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    ap.add_argument("--reboot", action="store_true", help="reboot and verify (needs --apply)")
    ap.add_argument("--only", nargs="+", help="use these hosts instead of HOSTS (user@ip)")
    ap.add_argument("--timeout", type=int, default=BOOT_TIMEOUT, help="seconds to wait for each host after reboot")

    a = ap.parse_args()
    if a.reboot and not a.apply:
        ap.error("--reboot needs --apply")
    targets = a.only or HOSTS
    failed = False
    with ThreadPoolExecutor(max_workers=len(targets)) as ex:
        for host, out, err in ex.map(lambda h: process(h, a.apply, a.reboot, a.timeout), targets):
            print(f"=== {host} ===")
            print(out or f"ERROR : {err}")
            print()
            failed |= err is not None
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
