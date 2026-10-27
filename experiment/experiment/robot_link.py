#one persistent SSH/SFTP connection to the robot for the whole session (lab 3 reconnected for every file)
import os
import threading

import config


class RobotLink:
    def __init__(self, robot_ip, user=config.ROBOT_USER, password=config.ROBOT_PASS):
        self.robot_ip = robot_ip
        self.user = user
        self.password = password
        self.ssh = None
        self.sftp = None
        self._lock = threading.Lock()  #paramiko SFTP channels are not safe to share between threads
        self.connect()

    def connect(self):
        import paramiko
        self.close()
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(self.robot_ip, username=self.user, password=self.password)
        self.ssh.get_transport().set_keepalive(15)
        self.sftp = self.ssh.open_sftp()
        self.run(f"mkdir -p {config.ROBOT_WORK_DIR}")

    #runs a shell command on the robot and waits for it to finish
    def run(self, command):
        _, stdout, _ = self.ssh.exec_command(command)
        return stdout.channel.recv_exit_status()

    #retries once after reconnecting, so a dropped connection does not end the session
    def _with_retry(self, fn):
        import paramiko
        with self._lock:
            try:
                return fn()
            except (paramiko.SSHException, EOFError, OSError) as e:
                if isinstance(e, FileNotFoundError):
                    raise
                print(f"SFTP error ({e}); reconnecting once...")
                self.connect()
                return fn()

    def get(self, robot_path, local_path):
        self._with_retry(lambda: self.sftp.get(robot_path, local_path))

    def put(self, local_path, robot_path):
        self._with_retry(lambda: self.sftp.put(local_path, robot_path))

    def exists(self, robot_path):
        def check():
            try:
                self.sftp.stat(robot_path)
                return True
            except FileNotFoundError:
                return False
        return self._with_retry(check)

    def remove(self, robot_path):
        def rm():
            try:
                self.sftp.remove(robot_path)
            except FileNotFoundError:
                pass
        self._with_retry(rm)

    #removes the robot-side scratch folder (recordings, speech files, photos)
    def cleanup(self):
        try:
            with self._lock:
                self.run(f"rm -rf {config.ROBOT_WORK_DIR}")
        except Exception as e:
            print(f"Robot cleanup failed: {e}")

    def close(self):
        for obj in (self.sftp, self.ssh):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        self.sftp = None
        self.ssh = None


#stand-in used in dry-run: "robot" paths are just local paths
class LocalLink:
    def get(self, robot_path, local_path):
        if os.path.abspath(robot_path) != os.path.abspath(local_path):
            import shutil
            shutil.copyfile(robot_path, local_path)

    def put(self, local_path, robot_path):
        pass

    def exists(self, robot_path):
        return os.path.exists(robot_path)

    def remove(self, robot_path):
        pass

    def cleanup(self):
        pass

    def close(self):
        pass
