#lists which expression animations are installed for the configured posture, and optionally plays them
#usage: python tools/gesture_probe.py <robot_ip> [--posture Sit|Stand] [--play nod hi ...] [--list-all]
#  --list-all  prints every installed animations/Sit/* (or Stand/*) behavior, to fix SIT_ANIMATIONS in config.py
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config
from nao_proxy import NaoProxy, connect_robot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("robot_ip")
    parser.add_argument("--posture", default=config.POSTURE, choices=["Sit", "Stand"])
    parser.add_argument("--play", nargs="*", help="expression names to play one after another")
    parser.add_argument("--list-all", action="store_true")
    args = parser.parse_args()

    session = connect_robot(args.robot_ip)
    if session is None:
        return 1
    nao = NaoProxy(session)
    if not nao.animate:
        print("ALBehaviorManager not available")
        return 1

    table = config.SIT_ANIMATIONS if args.posture == "Sit" else config.STAND_ANIMATIONS
    print(f"Configured {args.posture} animations:")
    for name in config.EXPRESSIONS:
        path = table.get(name)
        installed = bool(path) and nao.animate.isBehaviorInstalled(path)
        print(f"  {name:<10} {'installed    ' if installed else 'NOT INSTALLED'} {path}")

    if args.list_all:
        prefix = f"animations/{args.posture}/"
        installed = sorted(b for b in nao.animate.getInstalledBehaviors() if b.startswith(prefix))
        print(f"\nAll installed {prefix}* behaviors ({len(installed)}):")
        for b in installed:
            print(f"  {b}")

    if args.play:
        nao.prepare_posture(args.posture)
        for name in args.play:
            print(f"Playing {name}...")
            _, status = nao.change_expression(name, posture=args.posture)
            print(f"  {status}")
            nao.wait_for_gestures(timeout=10)
            time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
