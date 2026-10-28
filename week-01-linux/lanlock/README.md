# lanlock

Lock the onboard LAN interface name on Debian servers (rename it to `lan1g`) **before** adding a PCIe network card.

## The problem

Linux names network cards by their PCIe slot (`enp4s0`, `enp5s0`, ...). When a new card is installed, the slot numbers can shift and the onboard LAN gets a different name. `/etc/network/interfaces` still points at the old name, so the machine comes up with no network.

## The fix

Pin the name to the card's permanent MAC address with a systemd `.link` file, and update the network config to use the new name. After that, the name no longer depends on the slot.

`rename_iface.py` does this over SSH on many hosts at once:

1. Finds the single physical NIC that is UP and reads its permanent MAC.
2. Writes `/etc/systemd/network/10-lan1g.link` (`PermanentMACAddress=` + `Type=ether`).
3. Checks with `udevadm test-builtin` that udev will really apply the file.
4. Backs up `/etc/network/interfaces` and every other file it edits (dated copies) and replaces the old name in `/etc/network`.
5. Rebuilds the initramfs.
6. With `--reboot`: reboots and waits until `lan1g` is UP with an IPv4 address.

## Usage

```bash
./rename_iface.py                                   # dry-run: shows what would change, touches nothing
./rename_iface.py --apply                           # write files, no reboot
./rename_iface.py --apply --reboot                  # write files, reboot, verify
./rename_iface.py --apply --reboot --only user@192.0.2.11   # one host, ignore HOSTS
./rename_iface.py --apply --reboot --timeout 900    # slow hosts: wait longer for the reboot
```

Edit `HOSTS` at the top of the script first. Exit code is `1` if any host failed or was not rebooted.

**Requirements:** SSH key login (`BatchMode`), passwordless `sudo` on the hosts, Debian with ifupdown (`/etc/network/interfaces`) and systemd.

## Safety

- Dry-run is the default; nothing changes without `--apply`.
- Safe to rerun: hosts that already have `lan1g` are skipped, and the backup is never overwritten on a same-day rerun.
- The script **does not reboot** a host when the old name is still used outside `/etc/network` (firewall, DHCP, Docker, ...) or when no network file uses the new name. It prints the lines to fix, then you rerun.
- Without `--only`, `--reboot` reboots **all** hosts in `HOSTS` at the same time. If one of them is a gateway or DNS server for the others, do them one at a time.
- Keep console access (monitor + keyboard) ready in case a host does not come back.

### Rollback on a host

```bash
for b in /etc/network/*.bak.<YYYY-MM-DD> /etc/network/*/*.bak.<YYYY-MM-DD>; do sudo cp "$b" "${b%.bak.*}"; done
sudo rm /etc/systemd/network/10-lan1g.link && sudo update-initramfs -u
sudo reboot
```

## Limits

- Expects exactly one physical NIC whose name starts with `e` and is UP. Anything else stops the script for that host.
- Refuses a NIC that uses a spoofed MAC (`PermanentMACAddress` would not match).
- ifupdown only. Hosts managed by NetworkManager or systemd-networkd get the `.link` file but no config edit, so the reboot is skipped.
- Naming the new 10GbE card (e.g. `lan10g`) is not covered. After installing it, boot once, read its MAC with `ip -br link`, and create `10-lan10g.link` the same way.

## Tests

```bash
python3 test_pick_nic.py
```

Covers the NIC selection logic (VLANs, down cards, two cards UP, no card). The SSH and file-editing steps are not unit-tested; they were checked by running on real hosts.
