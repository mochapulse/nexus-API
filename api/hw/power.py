import subprocess
import sys


def system_poweroff():
    """Initiates an immediate, non-interactive power off for Linux servers."""
    try:
        # --no-ask-password: Prevents Polkit/systemd from popping up authentication prompts
        # --no-wall: Suppresses warning messages sent to terminal sessions
        subprocess.run(
            ["systemctl", "poweroff", "--no-ask-password", "--no-wall"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        print("Power-off command executed successfully.")
    except subprocess.CalledProcessError as e:
        print(
            f"Power-off failed: {e.stderr.strip()}",
            file=sys.stderr,
        )

def system_sleep():
    """Initiates an immediate, non-interactive sleep (suspend) for Linux servers."""
    try:
        # --no-ask-password: Prevents Polkit/systemd from popping up authentication prompts
        # --no-wall: Suppresses warning messages sent to terminal sessions
        subprocess.run(
            ["systemctl", "suspend", "--no-ask-password", "--no-wall"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        print("Sleep command executed successfully.")
    except subprocess.CalledProcessError as e:
        print(
            f"Sleep failed: {e.stderr.strip()}",
            file=sys.stderr,
        )