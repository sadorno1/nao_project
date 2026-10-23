
import sys, time, os, qi
import threading
import time
import tkinter as tk


if len(sys.argv) > 1 and len(sys.argv) < 3: #ensures proper number of arguments
    ROBOT_IP = sys.argv[1]
    ROBOT_PORT = 9559
else:
    print("please provide proper number of arguments")
    print("Proper program usage: python3 name.py IP_ADDRESS_HERE")
    sys.exit(1)


session = qi.Session()
try:
    print(f"Connecting to NAO at {ROBOT_IP}:{ROBOT_PORT}...")
    session.connect(f"tcp://{ROBOT_IP}:{ROBOT_PORT}")
    print("Successfully connected to NAO!")
    NAO_CONNECTED = True
except RuntimeError as e:
    print(f"Failed to connect to the robot at {ROBOT_IP}: {e}")
    print("Please try again")
    NAO_CONNECTED = False
    sys.exit(1)

try:
    tts = session.service("ALTextToSpeech") #initialized text-to-speech service
    motion = session.service("ALMotion")
    posture = session.service("ALRobotPosture")
    leds = session.service("ALLeds")


except Exception as e:
    print(f"Failed to load services: {e}")
    sys.exit(1)

#Helper functions
def run(fn, *args):
    if NAO_CONNECTED:
        threading.Thread(target=fn, args=args, daemon=True).start()

def say(text):
    run(tts.say, text)

def eye_color(r, g, b):
    run(leds.fadeRGB, "FaceLeds", r, g, b, 0.5)

def postures(name):
    run(posture.goToPosture, name, 0.5)

def do_nod():
    def _():
        motion.setAngles("HeadPitch", 0.3, 0.7)
        time.sleep(0.7)
        motion.setAngles("HeadPitch", 0, 0.7)
    run(_)

def surprise():
    def _():
        names = ["HeadPitch","LShoulderPitch", "LShoulderRoll", "LElbowYaw", "LElbowRoll","RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll"]
        startle = [-0.3,# head tilts back
                   -0.5,  0.8, -1.0, -0.5,   # left arm out wide
                   -0.5, -0.8,  1.0,  0.5]   # right arm out wide
        rest    = [ 0.0,
                    1.5,  0.1, -1.2, -0.5,
                    1.5, -0.1,  1.2,  0.5]
        motion.setAngles(names, startle, 0.4)
        tts.say('wow')
        time.sleep(1.0)
        motion.setAngles(names, rest, 0.2)
    run(_)

def laugh():
    def _():
        motion.setAngles('HeadPitch', -0.3, 0.4)
        tts.say('ha ha ha ha')
        motion.setAngles('HeadPitch', 0, 0.4)

    run(_)

    
def happy_arm_movement():
    def _():
        tts.say('woohoo')
        names = ["LShoulderPitch", "RShoulderPitch"]        
        motion.setAngles(names, [-0.5, -0.5], 0.5)
        time.sleep(1.5)
        motion.setAngles(names, [1.5, 1.5], 0.5)
    run(_)

# Joystick movement
def move_for(vx, vy, seconds):
    def _():
        if NAO_CONNECTED:
            motion.move(vx, vy, 0.0)
            time.sleep(seconds)
            motion.move(0, 0, 0)
    threading.Thread(target=_, daemon=True).start()


#GUI 
root = tk.Tk()
root.title("Nao WoZ")
root.configure(bg="#fde8f0")
root.resizable(False, False)

PINK  = "#e75480"
LIGHT = "#fde8f0"
WHITE = "#ffffff"
DARK  = "#5c1a33"

outer = tk.Frame(root, bg=LIGHT, padx=14, pady=14)
outer.pack()

# Speech 
tk.Label(outer, text="Speech", bg=LIGHT, fg=DARK, font=("TkDefaultFont", 11, "bold")).pack(anchor="w")
tk.Frame(outer, bg=PINK, height=1).pack(fill="x", pady=(0, 6))

SCRIPTS = [
    ("Greeting","Hello! My name is Nao!"),
    ("Intro Exercise", "Today we're going to do an exercise called Three Good Things. We are going to reflect about things we  are grateful for this week"),
    ("Prompt share", "What's one thing you're grateful for?"),
    ("Grateful 1", "I am grateful because I was fully charged"),
    ("Second one","Now the second thing"),
    ("Third one","Now the third thing"),
    ("Thank you","Great job, thanks for sharing!"),
    ("Bye","Byeee"),
]

for i, (label, script) in enumerate(SCRIPTS):
    if i % 5 == 0:
        row = tk.Frame(outer, bg=LIGHT)
        row.pack(anchor="w", pady=2)
    tk.Button(row, text=label, bg=WHITE, fg=DARK, relief="solid", bd=1,
              padx=8, pady=4, cursor="hand2",
              command=lambda s=script: say(s)).pack(side="left", padx=2)

tk.Label(outer, text="Custom", bg=LIGHT, fg=DARK).pack(anchor="w", pady=(10, 2))
entry_row = tk.Frame(outer, bg=LIGHT)
entry_row.pack(fill="x")
entry = tk.Entry(entry_row, bg=WHITE, fg=DARK, relief="solid", bd=1)
entry.pack(side="left", fill="x", expand=True, ipady=5)
tk.Button(entry_row, text="Send", bg=PINK, fg=WHITE, relief="flat",
          padx=10, pady=5, cursor="hand2",
          command=lambda: say(entry.get().strip())).pack(side="left", padx=(6, 0))

# Non-verbal
tk.Label(outer, text="Non-verbal", bg=LIGHT, fg=DARK, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(14, 0))
tk.Frame(outer, bg=PINK, height=1).pack(fill="x", pady=(0, 6))

nv = tk.Frame(outer, bg=LIGHT)
nv.pack(anchor="w")

tk.Button(nv, text="Nod", bg=WHITE, fg=DARK, relief="solid", bd=1,
          padx=8, pady=4, cursor="hand2", command=do_nod).pack(side="left", padx=2)

tk.Button(nv, text="Surprise", bg=WHITE, fg=DARK, relief="solid", bd=1,
          padx=8, pady=4, cursor="hand2", command=surprise).pack(side="left", padx=2)

tk.Button(nv, text="Happy arm movement", bg=WHITE, fg=DARK, relief="solid", bd=1,
          padx=8, pady=4, cursor="hand2", command=happy_arm_movement).pack(side="left", padx=2)

tk.Button(nv, text="Laugh", bg=WHITE, fg=DARK,relief="solid", bd=1, 
          padx=8, pady=4, cursor="hand2", command=laugh).pack(side="left", padx=2)

# Eye color 
tk.Label(outer, text="Eye color", bg=LIGHT, fg=DARK, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(14, 0))
tk.Frame(outer, bg=PINK, height=1).pack(fill="x", pady=(0, 6))

eye_row = tk.Frame(outer, bg=LIGHT)
eye_row.pack(anchor="w")

for name, r, g, b, bg, fg in [
    ("White",1.0, 1.0, 1.0, "#ffffff", "#333"),
    ("Blue", 0.0, 0.4, 1.0, "#4fc3f7", "#000"),
    ("Green",0.0, 1.0, 0.3, "#66bb6a", "#000"),
    ("Pink",1.0, 0.3, 0.5, "#f48fb1", "#000"),
    ("Purple",0.6, 0.0, 1.0, "#ab47bc", "#fff"),
    ("Red", 1.0, 0.0, 0.0,"#ff0000", "#fff"),
    ("Off", 0.0, 0.0, 0.0, "#aaaaaa", "#333"),
]:
    tk.Button(eye_row, text=name, bg=bg, fg=fg, relief="solid", bd=1,
              padx=8, pady=4, cursor="hand2",
              command=lambda r=r, g=g, b=b: eye_color(r, g, b)).pack(side="left", padx=2)

# Posture 
tk.Label(outer, text="Posture", bg=LIGHT, fg=DARK, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(14, 0))
tk.Frame(outer, bg=PINK, height=1).pack(fill="x", pady=(0, 6))

pos_row = tk.Frame(outer, bg=LIGHT)
pos_row.pack(anchor="w")

for label, name in [("Stand", "StandInit"), ("Sit", "Sit"), ("Crouch", "Crouch")]:
    tk.Button(pos_row, text=label, bg=WHITE, fg=DARK, relief="solid", bd=1,
              padx=8, pady=4, cursor="hand2",
              command=lambda n=name: postures(n)).pack(side="left", padx=2)

# Joystick 
tk.Label(outer, text="Move", bg=LIGHT, fg=DARK, font=("TkDefaultFont", 11, "bold")).pack(anchor="w", pady=(14, 0))
tk.Frame(outer, bg=PINK, height=1).pack(fill="x", pady=(0, 6))
 
move_area = tk.Frame(outer, bg=LIGHT)
move_area.pack(anchor="w")
 
sec_frame = tk.Frame(move_area, bg=LIGHT)
sec_frame.pack(anchor="w", pady=(0, 6))
tk.Label(sec_frame, text="Seconds:", bg=LIGHT, fg=DARK).pack(side="left")
sec_entry = tk.Entry(sec_frame, bg=WHITE, fg=DARK, relief="solid", bd=1, width=5)
sec_entry.insert(0, "1")
sec_entry.pack(side="left", padx=(6, 0), ipady=3)
 
def get_secs():
    try:
        return max(0.1, min(float(sec_entry.get()), 10.0))
    except ValueError:
        return 1.0
 
SPEED = 0.25
 
dpad = tk.Frame(move_area, bg=LIGHT)
dpad.pack(anchor="w")
 
tk.Label(dpad, bg=LIGHT, width=10).grid(row=0, column=0)
tk.Button(dpad, text="↑  Forward", bg=WHITE, fg=DARK, relief="solid", bd=1,
          padx=10, pady=6, cursor="hand2",
          command=lambda: move_for(SPEED, 0, get_secs())
          ).grid(row=0, column=1, padx=2, pady=2)
tk.Label(dpad, bg=LIGHT, width=10).grid(row=0, column=2)
 
tk.Button(dpad, text="←  Left", bg=WHITE, fg=DARK, relief="solid", bd=1,
          padx=10, pady=6, cursor="hand2",
          command=lambda: move_for(0, SPEED, get_secs())
          ).grid(row=1, column=0, padx=2, pady=2)
tk.Button(dpad, text="Stop", bg=PINK, fg=WHITE, relief="flat",
          padx=10, pady=6, cursor="hand2",
          command=lambda: move_for(0, 0, 0.1)
          ).grid(row=1, column=1, padx=2, pady=2)
tk.Button(dpad, text="Right  →", bg=WHITE, fg=DARK, relief="solid", bd=1,
          padx=10, pady=6, cursor="hand2",
          command=lambda: move_for(0, -SPEED, get_secs())
          ).grid(row=1, column=2, padx=2, pady=2)
 
tk.Label(dpad, bg=LIGHT, width=10).grid(row=2, column=0)
tk.Button(dpad, text="↓  Back", bg=WHITE, fg=DARK, relief="solid", bd=1,
          padx=10, pady=6, cursor="hand2",
          command=lambda: move_for(-SPEED, 0, get_secs())
          ).grid(row=2, column=1, padx=2, pady=2)
tk.Label(dpad, bg=LIGHT, width=10).grid(row=2, column=2)

root.mainloop()
