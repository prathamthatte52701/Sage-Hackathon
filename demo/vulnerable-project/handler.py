import subprocess


def run_backup(path):
    try:
        subprocess.run("tar -czf backup.tar.gz " + path, shell=True)
    except:
        pass
