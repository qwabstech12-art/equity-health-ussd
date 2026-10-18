import subprocess

def run_command():
    command = "source venv/bin/activate && bash ./manage.sh run"
    subprocess.run(command, shell=True, executable="/bin/bash")

if __name__ == "__main__":
    run_command()
