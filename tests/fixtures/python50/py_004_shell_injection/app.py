import subprocess
def run_diagnostic(host: str):
    command = f"ping -c 1 {host}"
    return subprocess.run(command, shell=True, capture_output=True, text=True).stdout
