def open_application(app_name):
    import os
    import subprocess

    try:
        if os.name == 'nt':  # For Windows
            os.startfile(app_name)
        elif os.name == 'posix':  # For macOS and Linux
            subprocess.Popen(['open', app_name]) if os.uname().sysname == 'Darwin' else subprocess.Popen(app_name)
        return f"{app_name} opened successfully."
    except Exception as e:
        return f"Failed to open {app_name}: {str(e)}"


def close_application(app_name):
    import os
    import signal
    import subprocess

    try:
        if os.name == 'nt':  # For Windows
            os.system(f'taskkill /f /im {app_name}.exe')
        else:  # For macOS and Linux
            subprocess.call(['pkill', app_name])
        return f"{app_name} closed successfully."
    except Exception as e:
        return f"Failed to close {app_name}: {str(e)}"