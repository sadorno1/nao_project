#prints which ALMemory sensor keys fire when you touch each part of the robot
#usage: python tools/sensor_probe.py <robot_ip>      (Ctrl+C to stop)
#touch the front/middle/rear head, both foot bumpers, chest button and hands, and check the names
#match TALK_SENSOR_KEY and CHECK_SENSOR_KEYS in config.py
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config


def main():
    if len(sys.argv) < 2:
        print("usage: python tools/sensor_probe.py <robot_ip>")
        return 1
    robot_ip = sys.argv[1]

    import qi
    session = qi.Session()
    session.connect(f"tcp://{robot_ip}:{config.ROBOT_PORT}")
    memory = session.service("ALMemory")
    print(f"Connected to NAO at {robot_ip}")

    try:
        system = session.service("ALSystem")
        print(f"NAOqi version: {system.systemVersion()}")
    except Exception as e:
        print(f"Could not read NAOqi version: {e}")

    #show every touch/bumper/button related event this robot actually declares
    declared = []
    try:
        declared = [k for k in memory.getEventList()
                    if any(w in k for w in ("Tactil", "Touch", "Bumper", "Button"))]
    except Exception as e:
        print(f"getEventList failed: {e}")
    print("\nDeclared touch-related events on this robot:")
    for k in sorted(declared):
        print(f"  {k}")

    start = time.perf_counter()
    subscribers = []  #keep references, otherwise the subscribers are garbage collected

    def make_callback(key):
        def callback(value):
            print(f"[{time.perf_counter() - start:8.3f}s] {key:<28} = {value}")
        return callback

    keys = list(dict.fromkeys(config.PROBE_SENSOR_KEYS + [k for k in declared if not k.startswith("ALTouch")]))
    for key in keys + [config.PROBE_TOUCH_CHANGED_EVENT]:
        try:
            sub = memory.subscriber(key)
            sub.signal.connect(make_callback(key))
            subscribers.append(sub)
        except Exception as e:
            print(f"  could not subscribe to {key}: {e}")

    print(f"\nConfigured talk sensor:  {config.TALK_SENSOR_KEY} "
          f"({'declared' if config.TALK_SENSOR_KEY in declared else 'NOT declared on this robot'})")
    for key in config.CHECK_SENSOR_KEYS:
        print(f"Configured check sensor: {key} "
              f"({'declared' if key in declared else 'NOT declared on this robot'})")
    print("\nListening. Touch each part of the robot. Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
