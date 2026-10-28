# DevOps Journey 2026

This is my repository for learning DevOps in 2026.
I created it to keep my scripts and notes as I work through each topic.

## Goal
Build hands-on skills in Linux, Docker, CI/CD, AWS, Terraform and monitoring.

## Progress
- [ ] Week 1: Linux on a real server
- [ ] Week 2: Bash, networking, Git
- [ ] Week 3: Docker
- [ ] Week 4: CI/CD
- [ ] Week 5: AWS basics
- [ ] Week 6: Terraform
- [ ] Week 7: Monitoring and security
- [ ] Week 8: Capstone project

## Log
- **2026-10-26**: Created the repo and wrote the goal and weekly plan.
- **2026-10-28** (Week 1): Added [`lanlock`](week-01-linux/lanlock/), a Python script that locks the onboard LAN name to `lan1g` over SSH on many Debian hosts, so adding a PCIe network card does not break the network. It pins the name to the permanent MAC with a systemd `.link` file, updates `/etc/network`, rebuilds the initramfs, and can reboot and verify. Dry-run by default, with backups and a rollback procedure. The NIC selection logic has unit tests.