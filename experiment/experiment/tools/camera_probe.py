#checks which camera capture method works on this NAO and saves a sample image from each
#usage: python tools/camera_probe.py <robot_ip> [--set-head] [--out DIR]
#  --set-head  moves the head to HEAD_YAW / HEAD_PITCH from config.py first, so you can check the
#              framing of the marked build spot (this is the pose used for the whole session)
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import config


def try_photo_capture(session, ssh_sftp, out_dir):
    photo = session.service("ALPhotoCapture")
    photo.setCameraID(config.CAMERA_INDEX)
    photo.setResolution(config.PHOTO_RESOLUTION)
    photo.setPictureFormat("jpg")
    t0 = time.perf_counter()
    result = photo.takePicture(config.ROBOT_PHOTO_DIR, "probe")
    t_capture = time.perf_counter() - t0
    #takePicture returns the saved path(s); fall back to the expected name if it returns nothing useful
    if isinstance(result, (list, tuple)) and result and isinstance(result[0], str):
        robot_path = result[0]
    elif isinstance(result, str):
        robot_path = result
    else:
        robot_path = f"{config.ROBOT_PHOTO_DIR}/probe.jpg"
    local_path = os.path.join(out_dir, "probe_photocapture.jpg")
    t1 = time.perf_counter()
    ssh_sftp.get(robot_path, local_path)
    t_transfer = time.perf_counter() - t1
    return local_path, t_capture, t_transfer, f"takePicture returned {result!r}"


def try_video_device(session, out_dir):
    from PIL import Image
    video = session.service("ALVideoDevice")
    t0 = time.perf_counter()
    handle = video.subscribeCamera("camera_probe", config.CAMERA_INDEX, config.VIDEO_RESOLUTION, 11, 5)  #11 = kRGBColorSpace
    try:
        frame = video.getImageRemote(handle)
    finally:
        video.unsubscribe(handle)
    t_capture = time.perf_counter() - t0
    if not frame:
        raise RuntimeError("getImageRemote returned no image")
    width, height, data = frame[0], frame[1], frame[6]
    image = Image.frombytes("RGB", (width, height), bytes(data))
    local_path = os.path.join(out_dir, "probe_videodevice.jpg")
    image.save(local_path, "JPEG", quality=95)
    return local_path, t_capture, 0.0, f"{width}x{height}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("robot_ip")
    parser.add_argument("--set-head", action="store_true")
    parser.add_argument("--out", default=os.path.join(config.TMP_DIR, "camera_probe"))
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)

    import qi
    import paramiko
    session = qi.Session()
    session.connect(f"tcp://{args.robot_ip}:{config.ROBOT_PORT}")
    print(f"Connected to NAO at {args.robot_ip}")
    try:
        print(f"NAOqi version: {session.service('ALSystem').systemVersion()}")
    except Exception as e:
        print(f"Could not read NAOqi version: {e}")

    if args.set_head:
        motion = session.service("ALMotion")
        motion.setStiffnesses("Head", 1.0)
        motion.setAngles(["HeadYaw", "HeadPitch"], [config.HEAD_YAW, config.HEAD_PITCH], 0.1)
        time.sleep(1.5)
        print(f"Head set to yaw={config.HEAD_YAW} pitch={config.HEAD_PITCH}")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(args.robot_ip, username=config.ROBOT_USER, password=config.ROBOT_PASS)
    ssh.exec_command(f"mkdir -p {config.ROBOT_WORK_DIR}")[1].channel.recv_exit_status()
    sftp = ssh.open_sftp()

    results = {}
    for name, run in (("ALPhotoCapture", lambda: try_photo_capture(session, sftp, args.out)),
                      ("ALVideoDevice", lambda: try_video_device(session, args.out))):
        print(f"\n--- {name} ---")
        try:
            path, t_capture, t_transfer, detail = run()
            from PIL import Image
            with Image.open(path) as im:
                size = im.size
            print(f"OK  {detail}")
            print(f"    image size {size}, capture {t_capture:.2f}s, transfer {t_transfer:.2f}s")
            print(f"    saved to {path}")
            results[name] = True
        except Exception as e:
            print(f"FAILED: {e}")
            results[name] = False

    sftp.close()
    ssh.close()

    print("\nSummary:")
    for name, ok in results.items():
        print(f"  {name:<15} {'works' if ok else 'does not work'}")
    if results.get("ALPhotoCapture"):
        print("Set CAPTURE_METHOD = 'auto' or 'photo' in config.py (higher resolution).")
    elif results.get("ALVideoDevice"):
        print("Set CAPTURE_METHOD = 'video' in config.py.")
    else:
        print("Neither method worked; check the camera index and NAOqi services.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
