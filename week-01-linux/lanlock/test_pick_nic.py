"""Run: python3 test_pick_nic.py  (or pytest)"""
from rename_iface import pick_nic

ONE = """\
lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP>
enp4s0           UP             02:00:00:00:00:01 <BROADCAST,MULTICAST,UP,LOWER_UP>
enp4s0.100@enp4s0 UP            02:00:00:00:00:01 <BROADCAST,MULTICAST,UP,LOWER_UP>
docker0          DOWN           02:42:00:00:00:00 <NO-CARRIER,BROADCAST,MULTICAST,UP>
enp5s0           DOWN           02:00:00:00:00:02 <NO-CARRIER,BROADCAST,MULTICAST,UP>
"""


def test_picks_only_the_physical_up_nic():
    assert pick_nic(ONE) == ("enp4s0", "02:00:00:00:00:01")


def test_refuses_two_up_nics():
    two = ONE.replace("enp5s0           DOWN", "enp5s0           UP  ")
    try:
        pick_nic(two)
    except RuntimeError as e:
        assert "found 2" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_refuses_no_nic():
    try:
        pick_nic("lo UNKNOWN 00:00:00:00:00:00 <LOOPBACK>\n")
    except RuntimeError as e:
        assert "found 0" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
